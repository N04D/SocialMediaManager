from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .identifiers import validate_namespaced_id, validate_runtime_id

SECRET_VALUE_FRAGMENTS = ("password", "token", "secret", "credential", "api_key")


@dataclass(frozen=True)
class ComponentBinding:
    component: str

    def __post_init__(self) -> None:
        validate_runtime_id(self.component, field_name="binding.component")

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ComponentBinding:
        return cls(component=str(payload.get("component") or ""))


@dataclass(frozen=True)
class Install:
    install_id: str
    workspace_id: str
    provider: str
    account_ref: str
    component_bindings: dict[str, ComponentBinding] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    secret_refs: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True

    def __post_init__(self) -> None:
        validate_runtime_id(self.install_id, field_name="install_id")
        validate_runtime_id(self.workspace_id, field_name="workspace_id")
        validate_runtime_id(self.provider, field_name="provider")
        normalized_bindings: dict[str, ComponentBinding] = {}
        for capability_id, binding in self.component_bindings.items():
            normalized = validate_namespaced_id(capability_id, field_name="component_bindings.capability_id")
            normalized_bindings[normalized] = (
                binding if isinstance(binding, ComponentBinding) else ComponentBinding.from_dict(dict(binding))
            )
        object.__setattr__(self, "component_bindings", normalized_bindings)
        object.__setattr__(self, "config", self._safe_config(self.config))
        object.__setattr__(self, "secret_refs", tuple(str(item) for item in self.secret_refs))

    @staticmethod
    def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
        for key in config:
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_VALUE_FRAGMENTS) and not lowered.endswith("_ref"):
                raise ValueError("Install config may contain secret references, but not secret-shaped values.")
        return json.loads(json.dumps(config, sort_keys=True, ensure_ascii=True))

    def binding_for(self, capability_id: str) -> ComponentBinding | None:
        return self.component_bindings.get(capability_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_ref": self.account_ref,
            "component_bindings": {
                capability: binding.to_dict() for capability, binding in sorted(self.component_bindings.items())
            },
            "config": json.loads(json.dumps(self.config, sort_keys=True, ensure_ascii=True)),
            "enabled": self.enabled,
            "install_id": self.install_id,
            "provider": self.provider,
            "secret_refs": list(self.secret_refs),
            "workspace_id": self.workspace_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Install:
        return cls(
            install_id=str(payload.get("install_id") or ""),
            workspace_id=str(payload.get("workspace_id") or ""),
            provider=str(payload.get("provider") or ""),
            account_ref=str(payload.get("account_ref") or ""),
            component_bindings={
                str(capability): ComponentBinding.from_dict(dict(binding))
                for capability, binding in dict(payload.get("component_bindings") or {}).items()
                if isinstance(binding, dict)
            },
            config=dict(payload.get("config") or {}),
            secret_refs=tuple(str(item) for item in payload.get("secret_refs", [])),
            enabled=bool(payload.get("enabled", True)),
        )
