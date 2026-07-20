from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .contracts import MEDIA_PLUGIN_CONTRACT_VERSION


class MediaPluginService(Protocol):
    plugin_id: str

    def health_check(self) -> dict[str, Any]: ...


@dataclass
class MediaPluginRuntime:
    plugin_id: str
    capabilities: tuple[str, ...]
    required_storage_capabilities: tuple[str, ...] = ("media.storage.read", "media.storage.store")
    contract_version: str = MEDIA_PLUGIN_CONTRACT_VERSION
    service: MediaPluginService | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def health_check(self) -> dict[str, Any]:
        service_health = self.service.health_check() if self.service is not None else {"status": "ready"}
        return {
            "plugin_id": self.plugin_id,
            "media_plugin_contract_version": self.contract_version,
            "capabilities": list(self.capabilities),
            "required_storage_capabilities": list(self.required_storage_capabilities),
            **service_health,
        }
