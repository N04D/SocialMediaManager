"""Models for OS-level plugin sandboxing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SandboxPlatformCapability:
    platform: str
    architecture: str
    supported: bool
    production_ready: bool
    available_controls: list[str]
    missing_controls: list[str]
    status: str
    safe_error_code: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SandboxCompilationContext:
    install_record_id: str
    environment_id: str
    artifact_checksum: str
    environment_checksum: str
    distribution_status: str = "community"
    development_override: bool = False


@dataclass(frozen=True)
class PluginSandboxPolicy:
    id: str
    version: str
    plugin_id: str
    plugin_version: str
    distribution_status: str
    permissions: list[str]
    capabilities: list[str]
    platform: str
    enforcement_mode: str
    filesystem_policy: dict[str, Any]
    network_policy: dict[str, Any]
    syscall_policy: dict[str, Any]
    process_policy: dict[str, Any]
    ipc_policy: dict[str, Any]
    identity_policy: dict[str, Any]
    resource_policy_id: str
    required_controls: list[str]
    optional_controls: list[str]
    failure_policy: str
    development_override_allowed: bool
    checksum: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginSandboxPlan:
    id: str
    policy_id: str
    plugin_id: str
    plugin_version: str
    install_record_id: str
    environment_id: str
    platform: str
    architecture: str
    required_controls: list[str]
    resolved_controls: list[str]
    filesystem_mounts: list[dict[str, Any]]
    filesystem_rules: list[dict[str, Any]]
    network_rules: list[dict[str, Any]]
    syscall_rules: list[dict[str, Any]]
    process_rules: list[dict[str, Any]]
    identity_rules: list[dict[str, Any]]
    resource_rules: list[dict[str, Any]]
    expected_attestation: dict[str, Any]
    policy_checksum: str
    environment_checksum: str
    artifact_checksum: str
    created_at: str
    expires_at: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SandboxPreparationResult:
    sandbox_plan_id: str
    status: str
    prepared_controls: list[str]
    missing_controls: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginHostProcessSpec:
    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin: object | None = None
    stdout: object | None = None
    stderr: object | None = None


@dataclass(frozen=True)
class SandboxedProcess:
    process: Any
    process_instance_id: str
    sandbox_plan_id: str
    sandbox_status: str
    controls: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginSandboxAttestation:
    id: str
    sandbox_plan_id: str
    plugin_host_id: str
    process_instance_id: str
    platform: str
    enforcement_status: str
    enforced_controls: list[str]
    missing_controls: list[str]
    filesystem_status: str
    network_status: str
    syscall_status: str
    process_status: str
    identity_status: str
    resource_status: str
    platform_evidence: dict[str, Any]
    policy_checksum: str
    environment_checksum: str
    process_reference: str
    attested_at: str
    expires_at: str
    status: str
    warnings: list[str] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["process_reference"] = "redacted"
        return payload


@dataclass(frozen=True)
class PluginSandboxViolation:
    id: str
    plugin_id: str
    plugin_version: str
    host_id: str
    process_instance_id: str
    sandbox_plan_id: str
    occurred_at: str
    platform: str
    control: str
    operation: str
    action: str
    blocked: bool
    severity: str
    safe_resource_summary: str
    syscall_name: str = ""
    network_summary: str = ""
    filesystem_summary: str = ""
    call_context_id: str = ""
    execution_attempt_id: str = ""
    mutation_state: str = "not_started"
    safe_error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginSandboxHealth:
    platform: str
    controller_status: str
    supported: bool
    production_ready: bool
    required_controls: list[str]
    active_controls: list[str]
    missing_controls: list[str]
    degraded_controls: list[str]
    active_sandboxed_hosts: int
    unsandboxed_development_hosts: int
    violation_count: int
    severe_violation_count: int
    latest_integrity_scan: str
    safe_error_code: str = ""
    warnings: list[str] = field(default_factory=list)


def default_expiry(hours: int = 24) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


__all__ = [
    "PluginHostProcessSpec",
    "PluginSandboxAttestation",
    "PluginSandboxHealth",
    "PluginSandboxPlan",
    "PluginSandboxPolicy",
    "PluginSandboxViolation",
    "SandboxCompilationContext",
    "SandboxPlatformCapability",
    "SandboxPreparationResult",
    "SandboxedProcess",
    "default_expiry",
    "utc_now",
]
