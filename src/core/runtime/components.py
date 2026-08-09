from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .capabilities import CapabilityDescriptor
from .identifiers import validate_runtime_id


@dataclass(frozen=True)
class ComponentManifest:
    component_id: str
    provider: str
    version: str
    sdk_version: str
    capabilities: tuple[CapabilityDescriptor, ...] = field(default_factory=tuple)
    required_secrets: tuple[str, ...] = field(default_factory=tuple)
    config_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_runtime_id(self.component_id, field_name="component_id")
        validate_runtime_id(self.provider, field_name="provider")
        if not self.version.strip():
            raise ValueError("ComponentManifest version is required.")
        if not self.sdk_version.strip():
            raise ValueError("ComponentManifest sdk_version is required.")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "required_secrets", tuple(str(item) for item in self.required_secrets))

    def supports(self, capability_id: str) -> bool:
        return any(item.capability_id == capability_id for item in self.capabilities)

    def capability(self, capability_id: str) -> CapabilityDescriptor | None:
        return next((item for item in self.capabilities if item.capability_id == capability_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "component_id": self.component_id,
            "config_schema": json.loads(json.dumps(self.config_schema, sort_keys=True, ensure_ascii=True)),
            "metadata": json.loads(json.dumps(self.metadata, sort_keys=True, ensure_ascii=True)),
            "provider": self.provider,
            "required_secrets": list(self.required_secrets),
            "sdk_version": self.sdk_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ComponentManifest:
        return cls(
            component_id=str(payload.get("component_id") or ""),
            provider=str(payload.get("provider") or ""),
            version=str(payload.get("version") or ""),
            sdk_version=str(payload.get("sdk_version") or ""),
            capabilities=tuple(
                CapabilityDescriptor.from_dict(item)
                for item in payload.get("capabilities", [])
                if isinstance(item, dict)
            ),
            required_secrets=tuple(str(item) for item in payload.get("required_secrets", [])),
            config_schema=dict(payload.get("config_schema") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )
