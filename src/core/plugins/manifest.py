from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .dependencies import PluginDependency
from .errors import PluginValidationError


SUPPORTED_PLUGIN_API_VERSION = 1


class PluginType(StrEnum):
    CHANNEL = "channel"
    MEDIA = "media"
    PROVIDER = "provider"


class PluginStatus(StrEnum):
    DISCOVERED = "discovered"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"
    DISABLED = "disabled"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    plugin_api_version: int
    type: PluginType
    entrypoint: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[PluginDependency, ...] = field(default_factory=tuple)
    config_schema: dict[str, Any] = field(default_factory=dict)
    status: PluginStatus = PluginStatus.DISCOVERED

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PluginManifest":
        if not isinstance(payload, dict):
            raise PluginValidationError(
                "plugin_manifest.invalid_type",
                "Plugin manifest must be an object.",
            )
        errors: list[str] = []
        for field_name in ["id", "name", "version", "entrypoint"]:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name} is required.")

        api_version = payload.get("plugin_api_version")
        if not isinstance(api_version, int):
            errors.append("plugin_api_version is required and must be an integer.")

        try:
            plugin_type = PluginType(str(payload.get("type", "")))
        except ValueError:
            plugin_type = None
            errors.append(f"type must be one of {[item.value for item in PluginType]}.")

        capabilities = payload.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) and item.strip() for item in capabilities):
            errors.append("capabilities must be a list of non-empty strings.")

        raw_dependencies = payload.get("dependencies", [])
        dependencies: list[PluginDependency] = []
        if not isinstance(raw_dependencies, list):
            errors.append("dependencies must be a list.")
        else:
            for item in raw_dependencies:
                if isinstance(item, str) and item.strip():
                    dependencies.append(PluginDependency(capability=item))
                elif isinstance(item, dict):
                    try:
                        dependencies.append(
                            PluginDependency(
                                plugin_id=str(item.get("plugin_id") or ""),
                                capability=str(item.get("capability") or ""),
                                min_version=str(item.get("min_version") or ""),
                                optional=bool(item.get("optional", False)),
                            )
                        )
                    except ValueError as exc:
                        errors.append(str(exc))
                else:
                    errors.append("dependencies entries must be strings or objects.")

        config_schema = payload.get("config_schema", {})
        if not isinstance(config_schema, dict):
            errors.append("config_schema must be an object.")

        if errors:
            raise PluginValidationError(
                "plugin_manifest.invalid",
                "Plugin manifest is invalid.",
                {"errors": errors},
            )

        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            version=str(payload["version"]),
            plugin_api_version=int(api_version),
            type=plugin_type or PluginType.PROVIDER,
            entrypoint=str(payload["entrypoint"]),
            capabilities=tuple(str(item) for item in capabilities),
            dependencies=tuple(dependencies),
            config_schema=dict(config_schema),
        )

    def validate(self, *, supported_api_version: int = SUPPORTED_PLUGIN_API_VERSION) -> None:
        if self.plugin_api_version != supported_api_version:
            raise PluginValidationError(
                "plugin_manifest.incompatible_api_version",
                "Plugin API version is not supported.",
                {
                    "plugin_id": self.id,
                    "plugin_api_version": self.plugin_api_version,
                    "supported_plugin_api_version": supported_api_version,
                },
            )
