"""Public Plugin SDK manifest model and validator."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.plugins.manifest import PluginManifest as CorePluginManifest
from src.core.plugins.manifest import PluginType

from .capabilities import validate_capability, validate_permission, validate_plugin_id
from .contracts import PLUGIN_MANIFEST_SCHEMA_VERSION, PLUGIN_SDK_VERSION
from .errors import PluginManifestValidationError

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class PluginMaintainer:
    """Public maintainer metadata without requiring private contact details."""

    name: str
    role: str = ""
    contact_reference: str = ""


@dataclass(frozen=True)
class PluginManifest:
    """SDK v1 manifest model.

    The existing core manifest fields are preserved for compatibility; SDK
    metadata is optional for older built-in manifests and reported as warnings.
    """

    schema_version: str
    id: str
    name: str
    version: str
    plugin_type: str
    description: str
    entrypoint: str
    plugin_api_version: int
    sdk_contract_version: str = PLUGIN_SDK_VERSION
    framework_contract_versions: dict[str, str] = field(default_factory=dict)
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    optional_dependencies: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    secrets: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    health: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    maintainers: tuple[PluginMaintainer, ...] = field(default_factory=tuple)
    license: str = ""
    repository: str = ""
    documentation: str = ""
    distribution: str = "community"
    permissions: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PluginManifest:
        """Parse a manifest dict, accepting legacy core manifest aliases."""

        raw_type = str(payload.get("plugin_type") or payload.get("type") or "")
        maintainers = tuple(
            PluginMaintainer(
                name=str(item.get("name") or ""),
                role=str(item.get("role") or ""),
                contact_reference=str(item.get("contact_reference") or ""),
            )
            for item in payload.get("maintainers", [])
            if isinstance(item, dict)
        )
        return cls(
            schema_version=str(payload.get("schema_version") or PLUGIN_MANIFEST_SCHEMA_VERSION),
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            version=str(payload.get("version") or ""),
            plugin_type=raw_type,
            description=str(payload.get("description") or ""),
            entrypoint=str(payload.get("entrypoint") or ""),
            plugin_api_version=int(payload.get("plugin_api_version") or 0),
            sdk_contract_version=str(payload.get("sdk_contract_version") or payload.get("sdk_version") or ""),
            framework_contract_versions=dict(payload.get("framework_contract_versions") or {}),
            capabilities=tuple(str(item) for item in payload.get("capabilities") or ()),
            dependencies=tuple(
                dict(item) if isinstance(item, dict) else {"capability": str(item)}
                for item in payload.get("dependencies") or ()
            ),
            optional_dependencies=tuple(
                dict(item) for item in payload.get("optional_dependencies") or () if isinstance(item, dict)
            ),
            configuration_schema=dict(payload.get("configuration_schema") or payload.get("config_schema") or {}),
            secrets=tuple(dict(item) for item in payload.get("secrets") or () if isinstance(item, dict)),
            health=dict(payload.get("health") or {}),
            compatibility=dict(payload.get("compatibility") or {}),
            maintainers=maintainers,
            license=str(payload.get("license") or ""),
            repository=str(payload.get("repository") or ""),
            documentation=str(payload.get("documentation") or ""),
            distribution=str(
                payload.get("distribution")
                or ("builtin" if str(payload.get("id", "")).startswith("channel.") else "community")
            ),
            permissions=tuple(str(item) for item in payload.get("permissions") or ()),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> PluginManifest:
        """Load and validate a manifest JSON file."""

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        manifest = cls.from_dict(payload)
        validate_manifest(manifest)
        return manifest

    def to_core_manifest(self) -> CorePluginManifest:
        """Convert to the existing core manifest without changing core semantics."""

        return CorePluginManifest.from_dict(
            {
                "id": self.id,
                "name": self.name,
                "version": self.version,
                "plugin_api_version": self.plugin_api_version,
                "type": self.plugin_type,
                "entrypoint": self.entrypoint,
                "capabilities": list(self.capabilities),
                "dependencies": list(self.dependencies),
                "config_schema": self.configuration_schema,
            }
        )


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Validate a plugin manifest and return non-fatal warnings."""

    warnings: list[str] = []
    validate_plugin_id(manifest.id)
    if not manifest.name.strip():
        raise PluginManifestValidationError("plugin_manifest.name_missing", "Plugin name is required.")
    if not SEMVER_PATTERN.match(manifest.version):
        raise PluginManifestValidationError("plugin_manifest.invalid_semver", "Plugin version must be semantic.")
    if manifest.plugin_type not in {item.value for item in PluginType}:
        raise PluginManifestValidationError("plugin_manifest.invalid_type", "Plugin type is invalid.")
    if not manifest.entrypoint or manifest.entrypoint.startswith("/") or ".." in manifest.entrypoint:
        raise PluginManifestValidationError("plugin_manifest.invalid_entrypoint", "Entrypoint must be a module path.")
    if not manifest.sdk_contract_version:
        warnings.append("sdk_contract_version_missing")
    elif manifest.sdk_contract_version.split(".", maxsplit=1)[0] != PLUGIN_SDK_VERSION.split(".", maxsplit=1)[0]:
        raise PluginManifestValidationError(
            "plugin_manifest.incompatible_sdk", "Plugin SDK major version is incompatible."
        )
    for capability in manifest.capabilities:
        validate_capability(capability, plugin_id=manifest.id)
    for permission in manifest.permissions:
        validate_permission(permission)
    for secret in manifest.secrets:
        if any("default" in str(key).lower() and str(value) for key, value in secret.items()):
            raise PluginManifestValidationError(
                "plugin_manifest.secret_default", "Secrets must not include default values."
            )
    serialized = json.dumps(
        {
            "configuration_schema": manifest.configuration_schema,
            "secrets": manifest.secrets,
            "health": manifest.health,
            "compatibility": manifest.compatibility,
        },
        sort_keys=True,
    )
    if re.search(r"(^|[\"'\s])/(home|tmp|etc|var|usr)/", serialized):
        raise PluginManifestValidationError(
            "plugin_manifest.absolute_path", "Manifest must not contain absolute paths."
        )
    if not manifest.maintainers:
        warnings.append("maintainer_metadata_missing")
    if not manifest.license:
        warnings.append("license_missing")
    return warnings


def build_manifest(**kwargs: Any) -> PluginManifest:
    """Build and validate a manifest from keyword arguments."""

    payload = {
        "schema_version": PLUGIN_MANIFEST_SCHEMA_VERSION,
        "sdk_contract_version": PLUGIN_SDK_VERSION,
        "plugin_api_version": 1,
        **kwargs,
    }
    manifest = PluginManifest.from_dict(payload)
    validate_manifest(manifest)
    return manifest


__all__ = ["PluginManifest", "PluginMaintainer", "build_manifest", "validate_manifest"]
