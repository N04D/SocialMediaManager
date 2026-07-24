"""Local proxy objects for remote external channel plugins."""

from __future__ import annotations

from typing import Any

from .supervisor import PluginHostSupervisor


class RemoteChannelRuntimeProxy:
    def __init__(
        self,
        supervisor: PluginHostSupervisor,
        plugin_id: str,
        plugin_version: str,
        capabilities: list[str],
        permissions: list[str],
    ):
        self.supervisor = supervisor
        self.plugin_id = plugin_id
        self.plugin_version = plugin_version
        self.capabilities = capabilities
        self.permissions = permissions

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        host = self.supervisor.ensure_host(
            self.plugin_id, self.plugin_version, capabilities=self.capabilities, permissions=self.permissions
        )
        return host.call_raw(method, payload or {})

    async def start_connect(self, request: Any) -> dict[str, Any]:
        return self._call("channel.start_connect", _to_payload(request))

    async def complete_connect(self, request: Any) -> dict[str, Any]:
        return self._call("channel.complete_connect", _to_payload(request))

    async def disconnect(self, request: Any) -> dict[str, Any]:
        return self._call("channel.disconnect", _to_payload(request))

    async def get_status(self, request: Any) -> dict[str, Any]:
        return self._call("channel.get_status", _to_payload(request))

    async def check_session(self, request: Any) -> dict[str, Any]:
        return self._call("channel.check_session", _to_payload(request))

    async def publish(self, request: Any) -> dict[str, Any]:
        return self._call("channel.publish", _to_payload(request))

    async def collect_metrics(self, request: Any) -> dict[str, Any]:
        return self._call("channel.collect_metrics", _to_payload(request))

    async def health_check(self, request: Any) -> dict[str, Any]:
        return self._call("channel.health", _to_payload(request))

    async def integrity_check(self, request: Any) -> dict[str, Any]:
        return self._call("channel.integrity", _to_payload(request))


class RemoteChannelPluginProxy:
    def __init__(self, supervisor: PluginHostSupervisor, manifest: dict[str, Any]) -> None:
        self.supervisor = supervisor
        self.manifest = manifest

    def create_runtime(self, context: Any = None) -> RemoteChannelRuntimeProxy:
        return RemoteChannelRuntimeProxy(
            self.supervisor,
            str(self.manifest["id"]),
            str(self.manifest["version"]),
            list(self.manifest.get("capabilities", [])),
            list(self.manifest.get("permissions", [])),
        )

    def register(self, context: Any) -> None:
        if hasattr(context, "register_runtime_factory"):
            context.register_runtime_factory(self.manifest["id"], self.create_runtime)


def _to_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": value}


__all__ = ["RemoteChannelPluginProxy", "RemoteChannelRuntimeProxy"]
