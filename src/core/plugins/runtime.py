from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.browser.contracts import BROWSER_PROVIDER_CONTRACT_VERSION, browser_contract_compatibility

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

    def register_service(self, name: str, service: Any) -> None:
        if name in self.services:
            raise PluginCapabilityError(
                "plugin_runtime.duplicate_service",
                "Plugin service is already registered.",
                {"plugin_id": self.manifest.id, "service_name": name},
            )
        self.services[name] = service

    def service(self, name: str, *, require_ready: bool = True) -> Any:
        if require_ready and self.status != PluginStatus.READY:
            raise PluginCapabilityError(
                "plugin_runtime.service_not_ready",
                "Plugin is not ready to provide this service.",
                {"plugin_id": self.manifest.id, "service_name": name, "status": self.status.value},
            )
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
            and browser_contract_compatibility(
                str(
                    runtime.health.get("browser_provider_contract_version")
                    or runtime.manifest.config_schema.get("browser_provider_contract_version")
                    or BROWSER_PROVIDER_CONTRACT_VERSION
                )
            )
            != "incompatible"
        ]
        if preferred_provider_id:
            candidates = [runtime for runtime in candidates if runtime.manifest.id == preferred_provider_id]
        candidates = sorted(
            candidates,
            key=lambda runtime: (
                runtime.health.get("default_priority", 1000)
                if isinstance(runtime.health.get("default_priority", 1000), int)
                else 1000,
                runtime.manifest.id,
            ),
        )
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
