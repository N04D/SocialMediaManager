from __future__ import annotations

from dataclasses import dataclass, field

from .dependencies import PluginDependency
from .errors import PluginCapabilityError, PluginDependencyError, PluginValidationError
from .manifest import SUPPORTED_PLUGIN_API_VERSION, PluginManifest, PluginStatus


def _parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in value.split("."):
        if not item.isdigit():
            break
        parts.append(int(item))
    return tuple(parts)


@dataclass
class PluginRegistry:
    supported_api_version: int = SUPPORTED_PLUGIN_API_VERSION
    _plugins: dict[str, PluginManifest] = field(default_factory=dict)
    _capabilities: dict[str, list[str]] = field(default_factory=dict)

    def register(self, manifest: PluginManifest | dict) -> PluginManifest:
        resolved = PluginManifest.from_dict(manifest) if isinstance(manifest, dict) else manifest
        resolved.validate(supported_api_version=self.supported_api_version)
        if resolved.id in self._plugins:
            raise PluginValidationError(
                "plugin_manifest.duplicate_id",
                "A plugin with this id is already registered.",
                {"plugin_id": resolved.id},
            )
        self._plugins[resolved.id] = resolved
        for capability in resolved.capabilities:
            self._capabilities.setdefault(capability, []).append(resolved.id)
        return resolved

    def get(self, plugin_id: str) -> PluginManifest | None:
        return self._plugins.get(plugin_id)

    def providers_for(self, capability: str, *, enabled_only: bool = True) -> list[PluginManifest]:
        providers: list[PluginManifest] = []
        for plugin_id in self._capabilities.get(capability, []):
            manifest = self._plugins[plugin_id]
            if enabled_only and manifest.status in {
                PluginStatus.DISABLED,
                PluginStatus.ERROR,
                PluginStatus.INCOMPATIBLE,
            }:
                continue
            providers.append(manifest)
        return providers

    def require_provider_for(self, capability: str) -> PluginManifest:
        providers = self.providers_for(capability)
        if not providers:
            raise PluginCapabilityError(
                "plugin_capability.missing_provider",
                "No enabled provider is available for the requested capability.",
                {"capability": capability},
            )
        return providers[0]

    def validate_dependencies(self, manifest: PluginManifest | str) -> None:
        resolved = self._plugins[manifest] if isinstance(manifest, str) else manifest
        missing: list[dict[str, str]] = []
        incompatible: list[dict[str, str]] = []
        for dependency in resolved.dependencies:
            if dependency.optional:
                continue
            target = self._resolve_dependency(dependency)
            if target is None:
                missing.append(
                    {
                        "plugin_id": dependency.plugin_id,
                        "capability": dependency.capability,
                    }
                )
                continue
            if dependency.min_version and _parse_version(target.version) < _parse_version(dependency.min_version):
                incompatible.append(
                    {
                        "plugin_id": target.id,
                        "version": target.version,
                        "min_version": dependency.min_version,
                    }
                )
        if missing or incompatible:
            raise PluginDependencyError(
                "plugin_dependency.unsatisfied",
                "Plugin dependencies are not satisfied.",
                {"plugin_id": resolved.id, "missing": missing, "incompatible": incompatible},
            )

    def validate_all_dependencies(self) -> None:
        for manifest in self._plugins.values():
            self.validate_dependencies(manifest)

    def _resolve_dependency(self, dependency: PluginDependency) -> PluginManifest | None:
        if dependency.plugin_id:
            target = self._plugins.get(dependency.plugin_id)
            if target and target.status not in {PluginStatus.DISABLED, PluginStatus.ERROR, PluginStatus.INCOMPATIBLE}:
                return target
            return None
        if dependency.capability:
            providers = self.providers_for(dependency.capability)
            return providers[0] if providers else None
        return None
