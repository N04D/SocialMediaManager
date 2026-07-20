from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import channel_store
from src.core.browser import (
    BROWSER_PROVIDER_CONTRACT_VERSION,
    BrowserProfileBusyError,
    BrowserProfileStatus,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserUnavailableError,
    FileBackedBrowserProfileLockManager,
    HumanTakeoverRequest,
    HumanTakeoverStatus,
    browser_contract_payload,
)

from .config import AutoBrowserConfig
from .errors import (
    AutoBrowserConnectionError,
    AutoBrowserError,
    AutoBrowserNotReadyError,
    AutoBrowserResponseError,
    AutoBrowserSessionNotFoundError,
    AutoBrowserUnauthorizedError,
    AutoBrowserVersionError,
)
from .models import AutoBrowserReconciliationItem, AutoBrowserSessionMapping
from .session import AutoBrowserSession
from .target_resolver import AutoBrowserTargetResolver
from .transport import AutoBrowserHttpTransport, AutoBrowserTransport
from .uploads import SharedVolumeUploadTransfer

PROVIDER_ID = "provider.browser.autobrowser"
REQUIRED_OPERATIONS = {
    "create_session",
    "get_session",
    "close_session",
    "observe",
    "navigate",
    "click",
    "fill",
    "upload",
    "screenshot",
    "evaluate",
    "auth_profile",
    "human_takeover",
}


class AutoBrowserProvider:
    def __init__(
        self,
        *,
        config: Any | None = None,
        auto_browser_config: AutoBrowserConfig | None = None,
        transport: AutoBrowserTransport | None = None,
        lock_manager: FileBackedBrowserProfileLockManager | None = None,
        mapping_path: Path | None = None,
    ) -> None:
        self.config = auto_browser_config or AutoBrowserConfig.from_app_config(config or object())
        self.transport = transport or AutoBrowserHttpTransport(self.config)
        self.lock_manager = lock_manager or FileBackedBrowserProfileLockManager(channel_store.LOCKS_DIR)
        self.mapping_path = mapping_path or (channel_store.STUDIO_DATA_DIR / "auto_browser_sessions.json")
        self.revocations_path = channel_store.STUDIO_DATA_DIR / "auto_browser_auth_profile_revocations.json"
        self.target_resolver = AutoBrowserTargetResolver()
        self.upload_transfer = (
            SharedVolumeUploadTransfer(
                host_dir=Path(self.config.shared_upload_host_dir),
                controller_dir=self.config.shared_upload_controller_dir,
            )
            if self.config.shared_upload_host_dir
            else None
        )
        self.sessions: dict[str, AutoBrowserSession] = {}
        self._locks: dict[str, Any] = {}
        self._takeovers: dict[str, dict[str, Any]] = {}
        self._last_reconciliation: dict[str, Any] = {}

    def create_session(self, options: BrowserSessionOptions) -> AutoBrowserSession:
        self._ensure_configured()
        if options.profile_id in self.config.account_kill_switches:
            raise BrowserUnavailableError(
                "auto_browser.account_kill_switch",
                "Auto Browser is disabled for this account.",
                {"profile_id": options.profile_id},
            )
        health = self.health_check()
        if health.get("status") != "ready":
            raise BrowserUnavailableError(
                str(health.get("code") or "auto_browser.not_ready"),
                "Auto Browser provider is not ready.",
                {"status": health.get("status"), "messages": health.get("messages", [])},
            )
        local_session_id = f"session_{uuid4().hex}"
        lock = None
        remote_session_id = ""
        profile_name = self.auth_profile_name(options.profile_id)
        purpose = str(options.metadata.get("purpose") or "")
        job_id = str(options.metadata.get("job_id") or "")
        ownership = self._ownership_metadata(options.profile_id, local_session_id, purpose=purpose, job_id=job_id)
        profile_exists = False
        profile_revoked = self._is_auth_profile_revoked(profile_name)
        try:
            self.transport.get_auth_profile(profile_name)
            profile_exists = True
        except AutoBrowserSessionNotFoundError:
            profile_exists = False
        except AutoBrowserError:
            profile_exists = False
        try:
            if options.exclusive:
                lock = self.lock_manager.acquire(
                    options.profile_id,
                    owner=f"{PROVIDER_ID}:{local_session_id}",
                    session_id=local_session_id,
                    provider_id=PROVIDER_ID,
                    metadata={"purpose": purpose, "job_id": job_id},
                )
                self._locks[local_session_id] = lock
            remote_payload = {
                "name": local_session_id,
                "start_url": options.start_url or None,
            }
            if profile_exists and not profile_revoked:
                remote_payload["auth_profile"] = profile_name
            remote = self.transport.create_session(remote_payload)
            remote_session_id = str(remote.get("session_id") or remote.get("id") or "")
            if not remote_session_id:
                raise AutoBrowserError("Auto Browser did not return a session id.")
            mapping = AutoBrowserSessionMapping(
                local_session_id=local_session_id,
                remote_session_id=remote_session_id,
                provider_id=PROVIDER_ID,
                profile_id=options.profile_id,
                auth_profile_name=profile_name,
                purpose=purpose,
                job_id=job_id,
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
                last_remote_status=str(remote.get("status") or ""),
                application_id=ownership["application_id"],
                workspace_hash=ownership["workspace_hash"],
                channel_account_hash=ownership["channel_account_hash"],
            )
            self._save_mapping(mapping)
            session = AutoBrowserSession(
                mapping=mapping,
                transport=self.transport,
                target_resolver=self.target_resolver,
                upload_transfer=self.upload_transfer,
                on_close=self._close_local_session,
            )
            self.sessions[local_session_id] = session
            return session
        except BrowserProfileBusyError:
            raise
        except AutoBrowserError as exc:
            if remote_session_id:
                try:
                    self.transport.close_session(remote_session_id)
                except AutoBrowserError:
                    pass
            if lock is not None:
                lock.release()
            self._locks.pop(local_session_id, None)
            self._delete_mapping(local_session_id)
            raise self._to_browser_error(exc) from exc
        except Exception as exc:
            if remote_session_id:
                try:
                    self.transport.close_session(remote_session_id)
                except AutoBrowserError:
                    pass
            if lock is not None:
                lock.release()
            self._locks.pop(local_session_id, None)
            self._delete_mapping(local_session_id)
            raise BrowserUnavailableError(
                "auto_browser.session_create_failed",
                "Could not create an Auto Browser session.",
            ) from exc

    def close_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.close()
            return
        mapping = self._load_mappings().get(session_id)
        if mapping:
            try:
                self.transport.close_session(str(mapping.get("remote_session_id") or ""))
            except AutoBrowserError:
                pass
            self._delete_mapping(session_id)

    def get_session(self, session_id: str) -> AutoBrowserSession | None:
        return self.sessions.get(session_id)

    def profile_status(self, profile_id: str) -> BrowserProfileStatus:
        status = self.lock_manager.status(profile_id)
        return BrowserProfileStatus(
            profile_id=profile_id,
            available=not bool(status["busy"]),
            busy=bool(status["busy"]),
            stale=bool(status["stale"]),
            owner=str(status["owner"]),
            lock_path=str(status["lock_path"]),
        )

    def health_check(self) -> dict[str, Any]:
        messages = self.config.validate()
        operations = sorted(REQUIRED_OPERATIONS)
        contract = browser_contract_payload(implemented_provider_version=BROWSER_PROVIDER_CONTRACT_VERSION)
        if not self.config.enabled:
            return {
                "status": "disabled",
                "ok": False,
                "enabled": False,
                "compatibility": "misconfigured",
                "messages": ["Auto Browser provider is disabled."],
                "supported_operations": operations,
                "optional_operations_missing": [],
                "default_priority": 50,
                **contract,
            }
        if self.config.global_kill_switch:
            return self._health(
                "disabled",
                "auto_browser.global_kill_switch",
                ["Auto Browser global kill switch is enabled."],
                compatibility="disabled",
            )
        if messages:
            return self._health("error", "auto_browser.misconfigured", messages, compatibility="misconfigured")
        try:
            health = self.transport.health()
            ready = self.transport.ready()
            info = self.transport.server_info()
        except AutoBrowserUnauthorizedError:
            return self._health(
                "error",
                "auto_browser.unauthorized",
                ["Auto Browser authentication failed."],
                compatibility="unauthorized",
            )
        except (AutoBrowserConnectionError, AutoBrowserNotReadyError) as exc:
            return self._health(
                "degraded", exc.code, ["Auto Browser is unreachable or not ready."], compatibility="unreachable"
            )
        except AutoBrowserError as exc:
            return self._health(
                "degraded", exc.code, ["Auto Browser health check failed."], compatibility="unreachable"
            )
        version = str(info.get("version") or info.get("server_version") or "")
        compatible_versions = {self.config.expected_server_version}
        if self.config.expected_server_version in {"1.3.1", "1.4.0"}:
            compatible_versions.update({"1.3.1", "1.4.0"})
        if self.config.expected_server_version and version and version not in compatible_versions:
            return self._health(
                "error",
                "auto_browser.incompatible_version",
                [f"Auto Browser version {version} was not the expected {self.config.expected_server_version}."],
                compatibility="incompatible",
                version=version,
            )
        feature_payload = info.get("features") if isinstance(info.get("features"), dict) else {}
        missing = [
            item
            for item in ["takeover", "auth_profiles", "uploads", "evaluation", "screenshots"]
            if feature_payload and not feature_payload.get(item, True)
        ]
        if not self.config.shared_upload_host_dir and "uploads" not in missing:
            missing.append("uploads")
        status = "ready" if not missing else "degraded"
        return {
            "status": status,
            "ok": status == "ready",
            "enabled": True,
            "compatibility": "compatible" if status == "ready" else "compatible_with_warnings",
            "controller": self.config.safe_base_url(),
            "tested_server_version": "1.4.0",
            "tested_api_version": "1.3.1",
            "server_version": version,
            "transport": "rest",
            "health_status": str(health.get("status") or "ok"),
            "readiness_status": str(ready.get("status") or "ok"),
            "supported_operations": operations,
            "optional_operations_missing": missing,
            "messages": missing,
            "default_priority": 50,
            "reconciliation": self._safe_reconciliation_summary(),
            "auth_profile_capability": "available",
            "takeover_capability": "available" if "takeover" not in missing else "missing",
            "artifact_capability": "available" if "screenshots" not in missing else "missing",
            "upload_capability": "available" if "uploads" not in missing else "missing",
            "evaluation_capability": "available" if "evaluation" not in missing else "missing",
            "auth_profile_delete_capability": "available" if self.config.auth_profile_delete_enabled else "missing",
            "pilot_readiness": self.pilot_readiness(),
            **contract,
        }

    def request_human_takeover(self, request: HumanTakeoverRequest) -> dict[str, Any]:
        session = self.sessions.get(request.session_id)
        if session is None:
            raise BrowserProviderError("browser_session.missing", "Browser session is not available.")
        try:
            remote = self.transport.create_takeover(
                session.remote_session_id,
                {"reason": request.reason, "timeout_seconds": request.timeout_seconds},
            )
        except AutoBrowserError as exc:
            raise BrowserProviderError(exc.code, "Could not request human browser takeover.", exc.details) from exc
        takeover_id = f"takeover_{uuid4().hex}"
        session.mapping.takeover_status = HumanTakeoverStatus.REQUESTED.value
        self._takeovers[takeover_id] = {
            "takeover_id": takeover_id,
            "session_id": request.session_id,
            "remote_takeover_id": str(remote.get("takeover_id") or remote.get("id") or ""),
            "remote_viewer_available": bool(remote.get("viewer_url") or remote.get("url")),
            "status": HumanTakeoverStatus.REQUESTED.value,
            "created_at": channel_store.now_iso(),
        }
        return {
            "status": HumanTakeoverStatus.REQUESTED.value,
            "session_id": request.session_id,
            "takeover_id": takeover_id,
            "takeover_reference": f"/channels/takeover/{takeover_id}",
            "expires_in_seconds": request.timeout_seconds,
        }

    def save_auth_profile_for_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise BrowserProviderError("browser_session.missing", "Browser session is not available.")
        return self.transport.save_auth_profile(session.remote_session_id, session.mapping.auth_profile_name)

    def forget_auth_profile(self, profile_id: str) -> dict[str, Any]:
        if not self.config.auth_profile_delete_enabled:
            return self._mark_auth_profile_revoked(profile_id, reason="delete route not enabled")
        return self.transport.delete_auth_profile(self.auth_profile_name(profile_id))

    def auth_profile_status(self, profile_id: str) -> dict[str, Any]:
        profile_name = self.auth_profile_name(profile_id)
        revoked = self._auth_profile_revocation(profile_name)
        try:
            payload = self.transport.get_auth_profile(profile_name)
        except AutoBrowserError as exc:
            if exc.code == "auto_browser.session_not_found":
                return {
                    "exists": False,
                    "provider_id": PROVIDER_ID,
                    "auth_profile_reference": profile_name,
                    "status": "revoked_locally" if revoked else "missing",
                    "revoked_locally": bool(revoked),
                }
            return {
                "exists": False,
                "provider_id": PROVIDER_ID,
                "auth_profile_reference": profile_name,
                "error_code": exc.code,
                "status": "revoked_locally" if revoked else "unknown",
                "revoked_locally": bool(revoked),
            }
        return {
            "exists": True,
            "provider_id": PROVIDER_ID,
            "auth_profile_reference": profile_name,
            "created_at": str(payload.get("created_at") or ""),
            "last_used_at": str(payload.get("last_used_at") or ""),
            "status": "revoked_locally" if revoked else str(payload.get("status") or "available"),
            "revoked_locally": bool(revoked),
        }

    def forget_auth_profile_with_audit(
        self,
        profile_id: str,
        *,
        admin_reason: str,
        actor: str = "local-dashboard",
        previous_status: str = "",
    ) -> dict[str, Any]:
        if len(admin_reason.strip()) < 8:
            raise ValueError("forget login requires an explicit reason of at least 8 characters.")
        profile_name = self.auth_profile_name(profile_id)
        audit = {
            "timestamp": channel_store.now_iso(),
            "actor": actor,
            "channel_account_id": profile_id,
            "provider_id": PROVIDER_ID,
            "auth_profile_reference": profile_name,
            "previous_status": previous_status,
            "reason": admin_reason.strip(),
            "remote_delete_result": "not_attempted",
            "local_status_update": "not_attempted",
            "error_code": "",
        }
        try:
            delete_result = self.forget_auth_profile(profile_id)
            audit["remote_delete_result"] = str(delete_result.get("status") or delete_result.get("deleted") or "ok")
            audit["local_status_update"] = "authentication_required"
            result = {
                "ok": True,
                "auth_profile_reference": profile_name,
                "delete_result": audit["remote_delete_result"],
            }
        except AutoBrowserResponseError as exc:
            if exc.details.get("status") in {404, 405}:
                revoked = self._mark_auth_profile_revoked(profile_id, reason="delete route unavailable")
                audit["remote_delete_result"] = "route_unavailable"
                audit["local_status_update"] = "revoked_locally"
                result = {
                    "ok": True,
                    "auth_profile_reference": profile_name,
                    "delete_result": "revoked_locally",
                    "revoked_locally": True,
                    "revocation": revoked,
                }
            else:
                audit["remote_delete_result"] = "failed"
                audit["error_code"] = exc.code
                result = {"ok": False, "auth_profile_reference": profile_name, "error_code": exc.code}
        except AutoBrowserSessionNotFoundError:
            revoked = self._mark_auth_profile_revoked(profile_id, reason="remote profile missing")
            audit["remote_delete_result"] = "remote_missing"
            audit["local_status_update"] = "revoked_locally"
            result = {
                "ok": True,
                "auth_profile_reference": profile_name,
                "delete_result": "revoked_locally",
                "revoked_locally": True,
                "revocation": revoked,
            }
        except AutoBrowserError as exc:
            audit["remote_delete_result"] = "failed"
            audit["error_code"] = exc.code
            result = {"ok": False, "auth_profile_reference": profile_name, "error_code": exc.code}
        self._append_audit("auto_browser_forget_login_audit.jsonl", audit)
        return result

    def reconcile_sessions(self) -> dict[str, Any]:
        mappings = self._load_mappings()
        try:
            remote_sessions = self.transport.list_sessions()
        except AutoBrowserError as exc:
            summary = {
                "status": "unavailable",
                "error_code": exc.code,
                "items": [],
                "orphaned_remote_count": 0,
                "stale_mapping_count": len(mappings),
                "checked_at": channel_store.now_iso(),
            }
            self._last_reconciliation = summary
            return summary
        remote_by_id = {
            str(item.get("session_id") or item.get("id") or ""): item
            for item in remote_sessions
            if isinstance(item, dict) and str(item.get("session_id") or item.get("id") or "")
        }
        items: list[AutoBrowserReconciliationItem] = []
        mapped_remote_ids: set[str] = set()
        for local_id, mapping in mappings.items():
            remote_id = str(mapping.get("remote_session_id") or "")
            mapped_remote_ids.add(remote_id)
            profile_id = str(mapping.get("profile_id") or "")
            if remote_id in remote_by_id:
                items.append(
                    AutoBrowserReconciliationItem(
                        kind="mapping_remote_match",
                        local_session_id=local_id,
                        remote_session_id=remote_id,
                        profile_id=profile_id,
                        status="active",
                        safe_to_cleanup=False,
                        message="Local mapping and remote session both exist.",
                    )
                )
            else:
                items.append(
                    AutoBrowserReconciliationItem(
                        kind="stale_mapping",
                        local_session_id=local_id,
                        remote_session_id=remote_id,
                        profile_id=profile_id,
                        status="remote_missing",
                        safe_to_cleanup=True,
                        message="Local mapping exists but remote session is missing.",
                    )
                )
        for remote_id, remote in remote_by_id.items():
            if remote_id in mapped_remote_ids:
                continue
            if self._owns_remote_session(remote):
                items.append(
                    AutoBrowserReconciliationItem(
                        kind="orphaned_remote_session",
                        remote_session_id=remote_id,
                        status=str(remote.get("status") or "unknown"),
                        safe_to_cleanup=False,
                        message="Remote session appears owned by this app but has no local mapping.",
                    )
                )
        stale = [item for item in items if item.kind == "stale_mapping"]
        orphaned = [item for item in items if item.kind == "orphaned_remote_session"]
        summary = {
            "status": "consistent" if not stale and not orphaned else "inconsistent_state",
            "checked_at": channel_store.now_iso(),
            "items": [item.__dict__ for item in items],
            "orphaned_remote_count": len(orphaned),
            "stale_mapping_count": len(stale),
        }
        self._last_reconciliation = summary
        return summary

    def cleanup_stale_mapping(self, local_session_id: str, *, admin_reason: str) -> dict[str, Any]:
        if len(admin_reason.strip()) < 8:
            raise ValueError("cleanup requires an explicit reason of at least 8 characters.")
        mappings = self._load_mappings()
        mapping = mappings.get(local_session_id)
        if not mapping:
            return {"ok": False, "status": "missing"}
        remote_id = str(mapping.get("remote_session_id") or "")
        try:
            self.transport.get_session(remote_id)
        except Exception:
            self._close_local_session(local_session_id)
            return {"ok": True, "status": "stale_mapping_removed"}
        return {"ok": False, "status": "remote_session_still_exists"}

    def force_unlock_profile(
        self, profile_id: str, *, admin_reason: str, actor: str = "local-dashboard"
    ) -> dict[str, Any]:
        return self.lock_manager.force_unlock(profile_id, admin_reason=admin_reason, actor=actor)

    def pilot_readiness(self) -> dict[str, Any]:
        reasons: list[str] = []
        if self.config.global_kill_switch:
            reasons.append("global_kill_switch")
        if not self.config.shared_upload_host_dir:
            reasons.append("shared_upload_unconfigured")
        if (self._last_reconciliation or {}).get("status") == "inconsistent_state":
            reasons.append("inconsistent_state")
        return {
            "status": "ready" if not reasons else "not_ready",
            "machine_readable": True,
            "provider_id": PROVIDER_ID,
            "reasons": reasons,
            "required_checks": [
                "health_ready",
                "shared_volume_upload_transfer",
                "provider_bound_auth_state",
                "takeover_reference_safe",
                "legacy_rollback_available",
            ],
        }

    def auth_profile_name(self, profile_id: str) -> str:
        raw = f"{Path.cwd()}:{profile_id}".encode()
        digest = hashlib.sha256(raw).hexdigest()[:24]
        prefix = "".join(ch for ch in self.config.auth_profile_prefix.lower() if ch.isalnum() or ch in {"-", "_"})[:24]
        return f"{prefix or 'smm'}-{digest}"

    def _ensure_configured(self) -> None:
        messages = self.config.validate()
        if not self.config.enabled or messages:
            raise BrowserUnavailableError(
                "auto_browser.misconfigured",
                "Auto Browser provider is not configured.",
                {"messages": messages},
            )

    def _close_local_session(self, session_id: str) -> None:
        lock = self._locks.pop(session_id, None)
        if lock is not None:
            lock.release()
        self.sessions.pop(session_id, None)
        self._delete_mapping(session_id)

    def _health(
        self,
        status: str,
        code: str,
        messages: list[str],
        *,
        compatibility: str,
        version: str = "",
    ) -> dict[str, Any]:
        return {
            "status": status,
            "ok": status == "ready",
            "enabled": self.config.enabled,
            "compatibility": compatibility,
            "controller": self.config.safe_base_url(),
            "code": code,
            "messages": messages,
            "server_version": version,
            "transport": "rest",
            "supported_operations": sorted(REQUIRED_OPERATIONS),
            "optional_operations_missing": [],
            "default_priority": 50,
            "reconciliation": self._last_reconciliation or {"status": "not_checked"},
            **browser_contract_payload(implemented_provider_version=BROWSER_PROVIDER_CONTRACT_VERSION),
        }

    @staticmethod
    def _to_browser_error(exc: AutoBrowserError) -> BrowserProviderError:
        if isinstance(exc, AutoBrowserVersionError):
            return BrowserUnavailableError(exc.code, "Auto Browser version is not compatible.", exc.details)
        if isinstance(exc, AutoBrowserUnauthorizedError):
            return BrowserUnavailableError(exc.code, "Auto Browser authentication failed.", exc.details)
        return BrowserUnavailableError(exc.code, "Auto Browser provider is unavailable.", exc.details)

    def _load_mappings(self) -> dict[str, dict[str, Any]]:
        if not self.mapping_path.exists():
            return {}
        try:
            payload = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _write_mappings(self, mappings: dict[str, dict[str, Any]]) -> None:
        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)
        self.mapping_path.write_text(json.dumps(mappings, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _save_mapping(self, mapping: AutoBrowserSessionMapping) -> None:
        mappings = self._load_mappings()
        mappings[mapping.local_session_id] = asdict(mapping)
        self._write_mappings(mappings)

    def _delete_mapping(self, session_id: str) -> None:
        mappings = self._load_mappings()
        if session_id in mappings:
            mappings.pop(session_id, None)
            self._write_mappings(mappings)

    def _load_revocations(self) -> dict[str, dict[str, Any]]:
        if not self.revocations_path.exists():
            return {}
        try:
            payload = json.loads(self.revocations_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _write_revocations(self, revocations: dict[str, dict[str, Any]]) -> None:
        self.revocations_path.parent.mkdir(parents=True, exist_ok=True)
        self.revocations_path.write_text(json.dumps(revocations, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _auth_profile_revocation(self, profile_name: str) -> dict[str, Any]:
        return self._load_revocations().get(profile_name, {})

    def _is_auth_profile_revoked(self, profile_name: str) -> bool:
        return bool(self._auth_profile_revocation(profile_name))

    def _mark_auth_profile_revoked(self, profile_id: str, *, reason: str) -> dict[str, Any]:
        profile_name = self.auth_profile_name(profile_id)
        revocations = self._load_revocations()
        revocation = {
            "provider_id": PROVIDER_ID,
            "auth_profile_reference": profile_name,
            "status": "revoked_locally",
            "revoked_at": channel_store.now_iso(),
            "reason": reason,
        }
        revocations[profile_name] = revocation
        self._write_revocations(revocations)
        return revocation

    def _ownership_metadata(
        self, profile_id: str, local_session_id: str, *, purpose: str, job_id: str
    ) -> dict[str, str]:
        workspace_hash = hashlib.sha256(str(Path.cwd()).encode()).hexdigest()[:16]
        channel_hash = hashlib.sha256(profile_id.encode()).hexdigest()[:16]
        return {
            "application_id": "social-media-manager",
            "provider_id": PROVIDER_ID,
            "workspace_hash": workspace_hash,
            "channel_account_hash": channel_hash,
            "local_session_id": local_session_id,
            "purpose": purpose,
            "job_id": job_id,
        }

    def _owns_remote_session(self, remote: dict[str, Any]) -> bool:
        metadata = remote.get("metadata") if isinstance(remote.get("metadata"), dict) else {}
        return metadata.get("application_id") == "social-media-manager" and metadata.get("provider_id") == PROVIDER_ID

    def _safe_reconciliation_summary(self) -> dict[str, Any]:
        try:
            summary = self.reconcile_sessions()
        except Exception:
            return {"status": "not_checked"}
        return {
            "status": summary.get("status", "unknown"),
            "checked_at": summary.get("checked_at", ""),
            "orphaned_remote_count": summary.get("orphaned_remote_count", 0),
            "stale_mapping_count": summary.get("stale_mapping_count", 0),
        }

    def _append_audit(self, filename: str, payload: dict[str, Any]) -> None:
        path = channel_store.STUDIO_DATA_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
