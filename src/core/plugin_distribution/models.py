"""Models for plugin package, registry, and installation distribution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class PluginSignerPolicy:
    id: str
    plugin_id: str
    distribution_status: str
    allowed_certificate_identities: tuple[str, ...]
    allowed_oidc_issuers: tuple[str, ...]
    allowed_repository: str = ""
    allowed_workflow_reference: str = ""
    minimum_signatures: int = 1
    require_transparency_log: bool = True
    require_signed_timestamp: bool = True
    active_from: str = ""
    active_until: str = ""
    revoked_identities: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginSignatureVerification:
    artifact_sha256: str
    signature_valid: bool
    bundle_valid: bool
    transparency_log_verified: bool
    signed_timestamp_verified: bool
    certificate_identity: str
    certificate_issuer: str
    identity_policy_id: str
    identity_matches: bool
    verified_at: str
    offline_verification: bool
    status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginReleaseMetadata:
    schema_version: str
    release_id: str
    plugin_id: str
    plugin_version: str
    distribution_name: str
    distribution_version: str
    distribution_status: str
    release_channel: str
    wheel_filename: str
    wheel_sha256: str
    wheel_size: int
    entrypoint_group: str
    entrypoint_name: str
    entrypoint_object: str
    plugin_sdk_version: str
    framework_contract_versions: dict[str, str]
    python_requires: str
    wheel_tags: tuple[str, ...]
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    maintainers: tuple[dict[str, Any], ...]
    signer_policy_id: str
    manifest_sha256: str
    sbom_sha256: str
    compatibility_report_sha256: str
    published_at: str
    yanked_at: str = ""
    revoked_at: str = ""
    minimum_host_version: str = ""
    maximum_host_version: str = ""
    state_schema_version: str = "1.0"
    minimum_readable_state_version: str = "1.0"
    maximum_readable_state_version: str = "1.0"
    migration_required: bool = False
    rollback_supported: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WheelInspectionResult:
    wheel_filename: str
    distribution_name: str
    distribution_version: str
    wheel_tags: tuple[str, ...]
    pure_python: bool
    record_verified: bool
    manifest: dict[str, Any]
    entrypoints: dict[str, str]
    dependencies: tuple[str, ...]
    file_count: int
    uncompressed_size: int
    top_level_modules: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginPackageVerificationResult:
    release_id: str
    plugin_id: str
    plugin_version: str
    artifact_sha256: str
    registry_verified: bool
    signature_verified: bool
    publisher_identity_verified: bool
    wheel_verified: bool
    record_verified: bool
    manifest_verified: bool
    entrypoint_verified: bool
    dependency_policy_passed: bool
    static_scan_passed: bool
    compatibility_passed: bool
    permissions: tuple[str, ...]
    risk_warnings: tuple[str, ...]
    blocking_errors: tuple[str, ...]
    verified_at: str
    report_checksum: str
    status: str


@dataclass(frozen=True)
class PluginRegistrySource:
    id: str
    name: str
    metadata_base_url: str
    targets_base_url: str
    trusted_root_path: str
    enabled: bool = True
    priority: int = 100
    official: bool = False
    allow_download: bool = False
    allow_install: bool = False
    last_refresh_at: str = ""
    last_success_at: str = ""
    status: str = "unconfigured"
    safe_error_code: str = ""


@dataclass(frozen=True)
class PluginRegistryEntry:
    plugin_id: str
    latest_version: str
    available_versions: tuple[str, ...]
    name: str
    description: str
    distribution_status: str
    release_channel: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    maintainers: tuple[dict[str, Any], ...]
    license: str
    sdk_compatibility: str
    signer_identity_summary: str
    yanked: bool
    revoked: bool
    published_at: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginInstallRecord:
    id: str
    plugin_id: str
    plugin_version: str
    release_id: str
    registry_source_id: str
    distribution_name: str
    artifact_sha256: str
    release_metadata_sha256: str
    sbom_sha256: str
    compatibility_report_sha256: str
    signer_identity: str
    signer_issuer: str
    identity_policy_id: str
    tuf_root_version: int
    tuf_timestamp_version: int
    tuf_snapshot_version: int
    tuf_targets_version: int
    permissions: tuple[str, ...]
    installed_file_manifest_checksum: str
    install_status: str
    installed_at: str
    installed_by: str
    enabled_at: str = ""
    enabled_by: str = ""
    disabled_at: str = ""
    uninstalled_at: str = ""
    previous_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginDistributionHealth:
    status: str
    framework_version: str
    registry_status: str
    trusted_root_version: int
    artifact_cache_status: str
    install_root_status: str
    active_external_plugins: int
    quarantined_releases: int
    revoked_active_releases: int
    incompatible_active_releases: int
    latest_integrity_scan: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginDistributionIntegrityFinding:
    code: str
    severity: str
    plugin_id: str = ""
    plugin_version: str = ""
    release_id: str = ""
    safe_message: str = ""
    repairable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [name for name in globals() if name.startswith("Plugin") or name == "WheelInspectionResult"]
