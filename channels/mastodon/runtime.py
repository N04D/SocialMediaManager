from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import channel_store
from channel_models import ChannelConnection
from src.core.plugins.manifest import PluginManifest

from .auth import MastodonOAuthService
from .client import MastodonApiClient
from .errors import MastodonError, MastodonScopeError, MastodonTokenError
from .instance import DEFAULT_SCOPES, MastodonInstanceService, normalize_instance_origin, requirements_from_snapshot
from .models import MastodonAccountState
from .status_policy import normalize_status
from .storage import (
    MastodonAccountRepository,
    MastodonAppRepository,
    MastodonInstanceRepository,
    MastodonOAuthFlowRepository,
    MastodonRemoteMediaRepository,
    MastodonRequirementsRepository,
    MastodonSecretStore,
    append_audit,
    append_event,
)
from .transport import HttpMastodonApiTransport


class MastodonChannelRuntime:
    service_name = "channel_runtime"

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        app_runtime: Any,
        config: Any,
        transport: Any | None = None,
        resolver: Any = None,
    ) -> None:
        self.manifest = manifest
        self.app_runtime = app_runtime
        self.config = config
        self.transport = transport or HttpMastodonApiTransport(
            allow_localhost_http=bool(getattr(config, "mastodon_allow_localhost_http", False)),
            resolver=resolver,
        )
        self.resolver = resolver
        self.accounts = MastodonAccountRepository()
        self.instances = MastodonInstanceRepository()
        self.requirements = MastodonRequirementsRepository()
        self.apps = MastodonAppRepository()
        self.flows = MastodonOAuthFlowRepository()
        self.secrets = MastodonSecretStore()

    def start_connect(
        self,
        *,
        workspace_id: str = "mastodon",
        channel_account_id: str = "",
        instance_origin: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        force_login: bool = False,
    ) -> dict[str, Any]:
        origin = self._normalize_origin(instance_origin)
        snapshot = self.discover(origin)
        account_id = (
            channel_account_id or f"mastodon:{snapshot.origin.removeprefix('https://').removeprefix('http://')}"
        )
        service = MastodonOAuthService(
            transport=self.transport,
            account_repository=self.accounts,
            app_repository=self.apps,
            flow_repository=self.flows,
            secret_store=self.secrets,
        )
        result = service.start_connect(
            workspace_id=workspace_id,
            channel_account_id=account_id,
            instance_origin=snapshot.origin,
            redirect_uri=redirect_uri,
            scopes=scopes or DEFAULT_SCOPES,
            force_login=force_login,
        )
        self._save_connection(account_id, "connecting", instance_snapshot=asdict(snapshot))
        return result | {"channel_account_id": account_id, "instance": self.safe_instance_payload(snapshot)}

    def complete_connect(self, *, code: str, state: str, workspace_id: str, channel_account_id: str) -> dict[str, Any]:
        service = MastodonOAuthService(
            transport=self.transport,
            account_repository=self.accounts,
            app_repository=self.apps,
            flow_repository=self.flows,
            secret_store=self.secrets,
        )
        account = service.complete_connect(
            code=code, state=state, workspace_id=workspace_id, channel_account_id=channel_account_id
        )
        snapshot = self.instances.latest_for_origin(account.instance_origin) or self.discover(account.instance_origin)
        requirements = requirements_from_snapshot(account.channel_account_id, snapshot)
        self.requirements.save(requirements)
        account.instance_snapshot_id = snapshot.id
        account.requirements_snapshot_id = requirements.id
        account.updated_at = channel_store.now_iso()
        self.accounts.save(account)
        self._save_connection(
            account.channel_account_id,
            "connected",
            account=account,
            instance_snapshot=asdict(snapshot),
            requirements=asdict(requirements),
        )
        append_event(
            "channel.mastodon.requirements.updated",
            workspace_id=account.workspace_id,
            account_id=account.channel_account_id,
            metadata={"checksum": requirements.checksum},
        )
        return self.safe_account_payload(account) | {"requirements": asdict(requirements)}

    def disconnect(self, *, channel_account_id: str, actor: str = "") -> dict[str, Any]:
        account = self.accounts.get(channel_account_id)
        if account is None:
            return {"status": "disconnected"}
        try:
            app = next((item for item in self.apps.list_all() if item.instance_origin == account.instance_origin), None)
            if app is not None and account.token_secret_ref:
                MastodonApiClient(origin=account.instance_origin, transport=self.transport).revoke_token(
                    client_id=self.secrets.get(app.client_id_secret_ref),
                    client_secret=self.secrets.get(app.client_secret_ref),
                    token=self.secrets.get(account.token_secret_ref),
                )
        except Exception:
            account.safe_error_code = "remote_revoke_failed"
        if account.token_secret_ref:
            self.secrets.revoke(account.token_secret_ref)
        account.revoked_local = True
        account.connection_status = "disconnected" if not account.safe_error_code else "remote_revoke_failed"
        account.updated_at = channel_store.now_iso()
        self.accounts.save(account)
        self._save_connection(channel_account_id, "disconnected", account=account)
        append_event(
            "channel.mastodon.disconnected", workspace_id=account.workspace_id, account_id=account.channel_account_id
        )
        append_audit(
            "disconnect",
            workspace_id=account.workspace_id,
            account_id=account.channel_account_id,
            actor=actor,
            result=account.connection_status,
        )
        return self.safe_account_payload(account)

    def status(self, *, channel_account_id: str = "") -> dict[str, Any]:
        if channel_account_id:
            account = self.accounts.get(channel_account_id)
            return self.safe_account_payload(account) if account else {"connection_status": "unconfigured"}
        return {"accounts": [self.safe_account_payload(item) for item in self.accounts.list_all()]}

    def check_session(self, *, channel_account_id: str, worker_id: str = "", started_at: str = "") -> dict[str, Any]:
        account = self.accounts.get(channel_account_id)
        if account is None or not account.token_secret_ref:
            raise MastodonTokenError("authentication_required", "Mastodon account is not connected.")
        try:
            token = self.secrets.get(account.token_secret_ref)
            remote = MastodonApiClient(
                origin=account.instance_origin, transport=self.transport, access_token=token
            ).verify_credentials()
            if str(remote.get("id") or "") != account.remote_account_id:
                account.connection_status = "security_error"
                account.safe_error_code = "account_mismatch"
            else:
                account.connection_status = "connected"
                account.safe_error_code = ""
                account.last_verified_at = channel_store.now_iso()
        except MastodonScopeError as exc:
            account.connection_status = "insufficient_scope"
            account.safe_error_code = exc.code
        except MastodonError as exc:
            account.connection_status = normalize_status(
                "authentication_required" if exc.http_status == 401 else "degraded"
            )
            account.safe_error_code = exc.code
        account.updated_at = channel_store.now_iso()
        self.accounts.save(account)
        self._save_connection(channel_account_id, account.connection_status, account=account)
        return self.safe_account_payload(account)

    def publish(self, job_id: str, *, worker_id: str = "", started_at: str = ""):
        from .worker.publish import run_publish_job_with_runtime

        return run_publish_job_with_runtime(
            self.config, self.app_runtime, job_id, worker_id=worker_id, started_at=started_at
        )

    def collect_metrics(self, job_id: str, *, worker_id: str = "", started_at: str = ""):
        from .worker.metrics import run_metric_job_with_runtime

        return run_metric_job_with_runtime(
            self.config, self.app_runtime, job_id, worker_id=worker_id, started_at=started_at
        )

    def health_check(self, *, channel_account_id: str = "") -> dict[str, Any]:
        account = self.accounts.get(channel_account_id) if channel_account_id else None
        requirements = self.requirements.latest_for_account(channel_account_id) if channel_account_id else None
        return {
            "status": "ready",
            "plugin_registered": True,
            "transport_available": self.transport is not None,
            "account_connected": bool(account and account.connection_status == "connected"),
            "instance_reachable": bool(account and account.instance_snapshot_id),
            "instance_supported": bool(account and not account.safe_error_code),
            "token_valid": bool(account and account.connection_status == "connected" and account.token_secret_ref),
            "scopes_sufficient": bool(account and set(DEFAULT_SCOPES) <= set(account.scope_set)),
            "requirements_snapshot_fresh": not _stale(requirements.expires_at) if requirements else False,
            "text_publish_supported": True,
            "image_publish_supported": True,
            "metrics_supported": True,
            "last_session_check": account.last_verified_at if account else "",
            "remote_orphan_media_count": sum(
                1
                for item in MastodonRemoteMediaRepository().list_all()
                if item.account_id == channel_account_id and not item.attached_status_id
            )
            if channel_account_id
            else 0,
            "safe_blockers": [account.safe_error_code] if account and account.safe_error_code else [],
        }

    def resolve_content_requirements(self, *, channel_account_id: str = "") -> dict[str, Any]:
        req = self.requirements.latest_for_account(channel_account_id) if channel_account_id else None
        if req is None:
            return {
                "channel_plugin_id": "channel.mastodon",
                "capability": "channel.publish.text",
                "max_body_length": 500,
                "stale": True,
            }
        return {
            "channel_plugin_id": "channel.mastodon",
            "capability": "channel.publish.text",
            "max_body_length": req.content_length_limit,
            "requirement_version": req.checksum,
            "stale": _stale(req.expires_at),
        }

    def resolve_media_requirements(self, *, channel_account_id: str = "") -> dict[str, Any]:
        req = self.requirements.latest_for_account(channel_account_id) if channel_account_id else None
        if req is None:
            return {
                "channel_plugin_id": "channel.mastodon",
                "capability": "channel.publish.image",
                "max_assets": 4,
                "stale": True,
            }
        return {
            "channel_plugin_id": "channel.mastodon",
            "capability": "channel.publish.image",
            "max_assets": req.maximum_media_count,
            "allowed_mime_types": req.supported_mime_types,
            "maximum_image_bytes": req.maximum_image_bytes,
            "maximum_image_pixels": req.maximum_image_pixels,
            "description_limit": req.description_limit,
            "requirement_version": req.checksum,
            "stale": _stale(req.expires_at),
        }

    def discover(self, instance_origin: str):
        snapshot = MastodonInstanceService(
            transport=self.transport,
            allow_localhost_http=bool(getattr(self.config, "mastodon_allow_localhost_http", False)),
            allowlist=list(getattr(self.config, "mastodon_instance_allowlist", []) or []),
            resolver=self.resolver,
        ).discover(instance_origin)
        self.instances.save(snapshot)
        append_event(
            "channel.mastodon.instance.discovered",
            metadata={"origin": snapshot.origin, "status": snapshot.software_status},
        )
        return snapshot

    def refresh_requirements(self, *, channel_account_id: str) -> dict[str, Any]:
        account = self.accounts.get(channel_account_id)
        if account is None:
            raise MastodonTokenError("authentication_required", "Mastodon account is not connected.")
        snapshot = self.discover(account.instance_origin)
        req = requirements_from_snapshot(account.channel_account_id, snapshot)
        self.requirements.save(req)
        account.instance_snapshot_id = snapshot.id
        account.requirements_snapshot_id = req.id
        self.accounts.save(account)
        return asdict(req)

    def integrity(self) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        seen_identity: set[tuple[str, str]] = set()
        for account in self.accounts.list_all():
            if not account.instance_origin:
                issues.append({"code": "mastodon.account_without_instance", "account_id": account.channel_account_id})
            if account.connection_status == "connected" and not account.token_secret_ref:
                issues.append(
                    {"code": "mastodon.connected_account_missing_secret", "account_id": account.channel_account_id}
                )
            identity = (account.instance_origin, account.remote_account_id)
            if account.remote_account_id and identity in seen_identity:
                issues.append({"code": "mastodon.duplicate_remote_account", "account_id": account.channel_account_id})
            seen_identity.add(identity)
            req = self.requirements.latest_for_account(account.channel_account_id)
            if req is None:
                issues.append({"code": "mastodon.requirements_missing", "account_id": account.channel_account_id})
            elif _stale(req.expires_at):
                issues.append({"code": "mastodon.requirements_stale", "account_id": account.channel_account_id})
        for media in MastodonRemoteMediaRepository().list_all():
            if not media.publication_target_id:
                issues.append({"code": "mastodon.remote_media_without_execution", "attachment_id": media.attachment_id})
            if media.attached_status_id and media.processing_status != "attached":
                issues.append({"code": "mastodon.attached_media_marked_orphan", "attachment_id": media.attachment_id})
        for issue in issues:
            append_event("channel.mastodon.integrity.issue_detected", metadata=issue)
        return {"issues": issues, "read_only": True}

    def safe_account_payload(self, account: MastodonAccountState | None) -> dict[str, Any]:
        if account is None:
            return {"connection_status": "unconfigured"}
        payload = asdict(account)
        payload["token_secret_ref"] = "present" if account.token_secret_ref and not account.revoked_local else ""
        return payload

    @staticmethod
    def safe_instance_payload(snapshot) -> dict[str, Any]:
        return asdict(snapshot)

    def _normalize_origin(self, value: str) -> str:
        return normalize_instance_origin(
            value,
            allow_localhost_http=bool(getattr(self.config, "mastodon_allow_localhost_http", False)),
            allowlist=list(getattr(self.config, "mastodon_instance_allowlist", []) or []) or None,
            resolver=self.resolver,
        )

    def _save_connection(
        self,
        account_id: str,
        status: str,
        *,
        account: MastodonAccountState | None = None,
        instance_snapshot: dict[str, Any] | None = None,
        requirements: dict[str, Any] | None = None,
    ) -> None:
        now = channel_store.now_iso()
        connection = ChannelConnection(
            id=f"connection_{account_id}",
            channel_id=account_id,
            mode="api_oauth_pkce",
            status=status,
            connected_at=account.connected_at if account else "",
            last_checked_at=now,
            last_error=account.safe_error_code if account else "",
            capabilities_snapshot_json={
                "channel_plugin_id": "channel.mastodon",
                "instance": instance_snapshot or {},
                "requirements": requirements or {},
            },
            created_at=account.created_at if account else now,
            updated_at=now,
            provider_connection_state_json={"instance_origin": account.instance_origin if account else ""},
        )
        channel_store.save_channel_connection(connection)


def _stale(expires_at: str) -> bool:
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at).astimezone(UTC) <= datetime.now(UTC)
    except ValueError:
        return True
