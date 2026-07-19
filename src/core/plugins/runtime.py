from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import PluginCapabilityError
from .manifest import PluginManifest, PluginStatus, PluginType
from .registry import PluginRegistry


@dataclass
class PluginRuntime:
    manifest: PluginManifest
    instance: Any = None
    status: PluginStatus = PluginStatus.DISCOVERED
    services: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)

    def service(self, name: str) -> Any:
        return self.services.get(name)


class ProviderResolver:
    def __init__(self, registry: PluginRegistry, runtimes: dict[str, PluginRuntime]) -> None:
        self.registry = registry
        self.runtimes = runtimes

    def resolve_provider(self, capability: str, *, preferred_provider_id: str = "") -> PluginRuntime:
        candidates = [
            runtime
            for runtime in self.runtimes.values()
            if runtime.manifest.type == PluginType.PROVIDER
            and capability in runtime.manifest.capabilities
            and runtime.status == PluginStatus.READY
        ]
        if preferred_provider_id:
            candidates = [runtime for runtime in candidates if runtime.manifest.id == preferred_provider_id]
        candidates = sorted(candidates, key=lambda runtime: runtime.manifest.id)
        if not candidates:
            raise PluginCapabilityError(
                "plugin_capability.provider_unavailable",
                "No ready provider is available for the requested capability.",
                {"capability": capability, "preferred_provider_id": preferred_provider_id},
            )
        return candidates[0]

    def resolve_service(self, capability: str, service_name: str, *, preferred_provider_id: str = "") -> Any:
        runtime = self.resolve_provider(capability, preferred_provider_id=preferred_provider_id)
        service = runtime.services.get(service_name)
        if service is None:
            raise PluginCapabilityError(
                "plugin_capability.service_unavailable",
                "The selected provider does not expose the requested service.",
                {"capability": capability, "service_name": service_name, "provider_id": runtime.manifest.id},
            )
        return service
