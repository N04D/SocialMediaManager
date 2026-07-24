"""Call-scoped host callback authorization and facades."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import PluginHostCallbackAuthorizationError, PluginHostPermissionError, PluginHostStateError
from .models import PluginHostCallContext
from .protocol import HOST_CALLBACK_METHODS


def _now() -> datetime:
    return datetime.now(UTC)


class PluginHostContextRegistry:
    def __init__(self) -> None:
        self._contexts: dict[str, PluginHostCallContext] = {}

    def create(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        workspace_id: str = "",
        channel_account_id: str = "",
        operation: str,
        capability: str,
        publication_target_id: str = "",
        execution_attempt_id: str = "",
        deadline: datetime,
        allowed_callbacks: list[str] | None = None,
        allowed_secrets: list[str] | None = None,
        allowed_media: list[str] | None = None,
        allowed_browser_provider: str = "",
    ) -> PluginHostCallContext:
        context = PluginHostCallContext(
            context_id=f"ctx_{uuid.uuid4().hex}",
            host_session=f"session_{uuid.uuid4().hex}",
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            workspace_id=workspace_id,
            channel_account_id=channel_account_id,
            operation=operation,
            capability=capability,
            publication_target_id=publication_target_id,
            execution_attempt_id=execution_attempt_id,
            deadline=deadline.isoformat(),
            allowed_callbacks=allowed_callbacks or sorted(HOST_CALLBACK_METHODS),
            allowed_secrets=allowed_secrets or [],
            allowed_media=allowed_media or [],
            allowed_browser_provider=allowed_browser_provider,
        )
        self._contexts[context.context_id] = context
        return context

    def authorize(self, context_id: str, method: str, plugin_id: str, plugin_version: str) -> PluginHostCallContext:
        context = self._contexts.get(context_id)
        if context is None or context.revoked:
            raise PluginHostCallbackAuthorizationError(
                "plugin_host.callback.context_revoked", "Plugin callback context is not active."
            )
        if context.plugin_id != plugin_id or context.plugin_version != plugin_version:
            raise PluginHostCallbackAuthorizationError(
                "plugin_host.callback.plugin_mismatch", "Plugin callback context does not match plugin."
            )
        if method not in context.allowed_callbacks:
            raise PluginHostPermissionError("plugin_host.callback.not_allowed", "Callback is not allowed in this call.")
        if datetime.fromisoformat(context.deadline) < _now():
            context.revoked = True
            raise PluginHostCallbackAuthorizationError(
                "plugin_host.callback.deadline_expired", "Plugin callback context deadline expired."
            )
        return context

    def revoke(self, context_id: str) -> None:
        context = self._contexts.get(context_id)
        if context is not None:
            context.revoked = True


class PluginHostStateStore:
    def __init__(
        self, state_root: str | Path, *, max_item_bytes: int = 64 * 1024, max_total_bytes: int = 5 * 1024 * 1024
    ):
        self.state_root = Path(state_root)
        self.max_item_bytes = max_item_bytes
        self.max_total_bytes = max_total_bytes

    def get(self, context: PluginHostCallContext, namespace: str, key: str) -> Any:
        path = self._path(context, namespace, key)
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, context: PluginHostCallContext, namespace: str, key: str, value: Any) -> dict[str, str]:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        if len(payload) > self.max_item_bytes:
            raise PluginHostStateError("plugin_host.state.item_too_large", "State item exceeds the configured limit.")
        if self._total_bytes(context.plugin_id) + len(payload) > self.max_total_bytes:
            raise PluginHostStateError("plugin_host.state.quota_exceeded", "Plugin state quota exceeded.")
        path = self._path(context, namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {"status": "stored", "checksum": hashlib.sha256(payload).hexdigest()}

    def delete(self, context: PluginHostCallContext, namespace: str, key: str) -> dict[str, str]:
        path = self._path(context, namespace, key)
        if path.exists():
            path.unlink()
        return {"status": "deleted"}

    def compare_and_set(
        self, context: PluginHostCallContext, namespace: str, key: str, expected: Any, value: Any
    ) -> dict[str, str]:
        current = self.get(context, namespace, key)
        if current != expected:
            return {"status": "not_matched"}
        return self.put(context, namespace, key, value)

    def _path(self, context: PluginHostCallContext, namespace: str, key: str) -> Path:
        for value in [namespace, key]:
            if not value or "/" in value or "\\" in value or ".." in value:
                raise PluginHostStateError("plugin_host.state.key_invalid", "State namespace or key is invalid.")
        return (
            self.state_root
            / context.plugin_id
            / context.workspace_id
            / context.channel_account_id
            / namespace
            / f"{key}.json"
        )

    def _total_bytes(self, plugin_id: str) -> int:
        root = self.state_root / plugin_id
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0


class PluginHostTransferStore:
    def __init__(self, transfer_root: str | Path) -> None:
        self.transfer_root = Path(transfer_root)
        self._transfers: dict[str, dict[str, Any]] = {}

    def materialize_from_path(
        self, context: PluginHostCallContext, source: str | Path, *, mime: str, checksum: str = "", expiry: str = ""
    ) -> dict[str, Any]:
        src = Path(source)
        if not src.is_file() or src.is_symlink():
            raise PluginHostPermissionError("plugin_host.media.invalid_source", "Media source is not a regular file.")
        transfer_id = f"transfer_{uuid.uuid4().hex}"
        self.transfer_root.mkdir(parents=True, exist_ok=True)
        target_dir = Path(tempfile.mkdtemp(prefix="transfer-", dir=self.transfer_root))
        target = target_dir / "media.bin"
        shutil.copyfile(src, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if checksum and digest != checksum:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise PluginHostPermissionError("plugin_host.media.checksum_mismatch", "Media checksum mismatch.")
        record = {
            "transfer_id": transfer_id,
            "context_id": context.context_id,
            "path": str(target),
            "mime": mime,
            "size": target.stat().st_size,
            "checksum": digest,
            "expiry": expiry,
        }
        self._transfers[transfer_id] = record
        return {key: value for key, value in record.items() if key != "context_id"}

    def release(self, context: PluginHostCallContext, transfer_id: str) -> dict[str, str]:
        record = self._transfers.pop(transfer_id, None)
        if record and record.get("context_id") == context.context_id:
            shutil.rmtree(Path(record["path"]).parent, ignore_errors=True)
            return {"status": "released"}
        raise PluginHostPermissionError(
            "plugin_host.media.transfer_denied", "Media transfer is not bound to this call."
        )


class PluginHostCallbackDispatcher:
    def __init__(self, contexts: PluginHostContextRegistry, state_store: PluginHostStateStore | None = None) -> None:
        self.contexts = contexts
        self.state_store = state_store
        self.history: list[dict[str, Any]] = []

    def dispatch(self, plugin_id: str, plugin_version: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        context = self.contexts.authorize(str(params.get("context_id") or ""), method, plugin_id, plugin_version)
        safe_params = {key: "***" if "secret" in key.lower() else value for key, value in params.items()}
        self.history.append({"method": method, "context": context.context_id, "params": safe_params})
        if method == "host.clock.now":
            return {"now": _now().isoformat()}
        if method.startswith("host.state.") and self.state_store is not None:
            namespace = str(params.get("namespace") or "default")
            key = str(params.get("key") or "")
            if method == "host.state.get":
                return {"value": self.state_store.get(context, namespace, key)}
            if method == "host.state.put":
                return self.state_store.put(context, namespace, key, params.get("value"))
            if method == "host.state.delete":
                return self.state_store.delete(context, namespace, key)
            if method == "host.state.compare_and_set":
                return self.state_store.compare_and_set(
                    context, namespace, key, params.get("expected"), params.get("value")
                )
        if method.startswith("host.secret."):
            purpose = str(params.get("purpose") or "")
            if purpose not in context.allowed_secrets:
                raise PluginHostPermissionError("plugin_host.secret.scope_denied", "Secret purpose is not allowed.")
            return {"status": "redacted"}
        if method == "host.http.request":
            if "host.http.request" not in context.allowed_callbacks:
                raise PluginHostPermissionError("plugin_host.http.denied", "HTTP callback is not allowed.")
            return {"status": "blocked_by_fixture", "body": None, "headers": {}}
        return {"status": "accepted"}


def public_context(context: PluginHostCallContext) -> dict[str, Any]:
    payload = asdict(context)
    payload.pop("allowed_secrets", None)
    return payload


__all__ = [
    "PluginHostCallbackDispatcher",
    "PluginHostContextRegistry",
    "PluginHostStateStore",
    "PluginHostTransferStore",
    "public_context",
]
