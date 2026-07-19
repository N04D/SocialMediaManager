from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import channel_store
from src.core.browser import (
    BrowserProfileBusyError,
    BrowserProfileStatus,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserUnavailableError,
    FileBackedBrowserProfileLockManager,
    HumanTakeoverRequest,
    HumanTakeoverStatus,
)

from .config import AutoBrowserConfig
from .errors import (
    AutoBrowserConnectionError,
    AutoBrowserError,
    AutoBrowserNotReadyError,
    AutoBrowserUnauthorizedError,
    AutoBrowserVersionError,
)
from .models import AutoBrowserSessionMapping
from .session import AutoBrowserSession
from .target_resolver import AutoBrowserTargetResolver
from .transport import AutoBrowserHttpTransport, AutoBrowserTransport

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
        self.target_resolver = AutoBrowserTargetResolver()
        self.sessions: dict[str, AutoBrowserSession] = {}
        self._locks: dict[str, Any] = {}
        self._takeovers: dict[str, dict[str, Any]] = {}

    def create_session(self, options: BrowserSessionOptions) -> AutoBrowserSession:
        self._ensure_configured()
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
            remote = self.transport.create_session(
                {
                    "name": local_session_id,
                    "start_url": options.start_url or None,
                    "auth_profile": profile_name,
                    "memory_profile": False,
                    "metadata": {
                        "provider_id": PROVIDER_ID,
                        "profile_id": options.profile_id,
                        "purpose": purpose,
                        "job_id": job_id,
                    },
                }
            )
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
            )
            self._save_mapping(mapping)
            session = AutoBrowserSession(
                mapping=mapping,
                transport=self.transport,
                target_resolver=self.target_resolver,
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
            }
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
        if self.config.expected_server_version and version and version != self.config.expected_server_version:
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
        status = "ready" if not missing else "degraded"
        return {
            "status": status,
            "ok": status == "ready",
            "enabled": True,
            "compatibility": "compatible" if status == "ready" else "compatible_with_warnings",
            "controller": self.config.safe_base_url(),
            "tested_server_version": "1.4.0",
            "server_version": version,
            "transport": "rest",
            "health_status": str(health.get("status") or "ok"),
            "readiness_status": str(ready.get("status") or "ok"),
            "supported_operations": operations,
            "optional_operations_missing": missing,
            "messages": missing,
            "default_priority": 50,
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
        return self.transport.delete_auth_profile(self.auth_profile_name(profile_id))

    def force_unlock_profile(
        self, profile_id: str, *, admin_reason: str, actor: str = "local-dashboard"
    ) -> dict[str, Any]:
        return self.lock_manager.force_unlock(profile_id, admin_reason=admin_reason, actor=actor)

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
