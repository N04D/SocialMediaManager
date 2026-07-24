"""Models for out-of-process plugin hosting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class PluginHostEnvironmentSpec:
    plugin_id: str
    plugin_version: str
    artifact_sha256: str
    manifest_checksum: str
    entrypoint: str
    environment_checksum: str = ""
    python_executable: str = ""
    status: str = "not_prepared"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginHostResourcePolicy:
    memory_bytes: int = 256 * 1024 * 1024
    cpu_seconds: int = 30
    open_files: int = 64
    process_count: int = 8
    created_file_bytes: int = 32 * 1024 * 1024
    core_dump_bytes: int = 0
    max_frame_bytes: int = 1024 * 1024
    max_concurrent_requests: int = 4
    stderr_bytes_per_minute: int = 64 * 1024
    max_transfers: int = 8
    max_transfer_bytes: int = 64 * 1024 * 1024
    request_timeout_seconds: float = 30.0
    shutdown_grace_seconds: float = 3.0
    terminate_grace_seconds: float = 2.0
    crash_window_seconds: int = 300
    maximum_crashes: int = 3
    restart_backoff_seconds: float = 1.0
    platform_status: str = "unknown"


@dataclass
class PluginHostHandshake:
    protocol_version: str
    host_runtime_version: str
    plugin_sdk_version: str
    expected_plugin_id: str
    expected_plugin_version: str
    manifest_checksum: str
    artifact_checksum: str
    entrypoint: str
    allowed_capabilities: list[str]
    allowed_permissions: list[str]
    maximum_frame_size: int
    session_nonce: str
    environment_checksum: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginReady:
    protocol_version: str
    plugin_id: str
    plugin_version: str
    manifest_checksum: str
    entrypoint_identity: str
    plugin_sdk_version: str
    capabilities: list[str]
    requested_permissions: list[str]
    supported_methods: list[str]
    runtime_checksum: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class PluginHostCallContext:
    context_id: str
    host_session: str
    plugin_id: str
    plugin_version: str
    workspace_id: str
    channel_account_id: str
    operation: str
    capability: str
    publication_target_id: str
    execution_attempt_id: str
    deadline: str
    allowed_callbacks: list[str]
    allowed_secrets: list[str] = field(default_factory=list)
    allowed_media: list[str] = field(default_factory=list)
    allowed_browser_provider: str = ""
    revoked: bool = False


@dataclass
class PluginHostProcessRecord:
    host_id: str
    plugin_id: str
    plugin_version: str
    execution_mode: str = "external_process"
    environment_status: str = "not_prepared"
    process_status: str = "stopped"
    protocol_version: str = "1.0"
    last_heartbeat_at: str = ""
    active_calls: int = 0
    memory_status: str = "unknown"
    cpu_status: str = "unknown"
    crash_count: int = 0
    restart_backoff_seconds: float = 0
    crash_classification: str = ""
    resource_containment: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginHostCrashRecord:
    host_id: str
    plugin_id: str
    plugin_version: str
    classification: str
    mutation_state: str
    occurred_at: str = field(default_factory=utc_now)
    safe_error_code: str = ""
    safe_message: str = ""
    restartable: bool = False
    stderr_excerpt: str = ""


@dataclass
class PluginHostIntegrityFinding:
    code: str
    severity: str
    plugin_id: str = ""
    plugin_version: str = ""
    host_id: str = ""
    safe_message: str = ""
    repairable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginHostHealth:
    status: str
    framework_version: str
    protocol_version: str
    active_hosts: int
    degraded_hosts: int
    resource_containment: str
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "PluginHostCallContext",
    "PluginHostCrashRecord",
    "PluginHostEnvironmentSpec",
    "PluginHostHandshake",
    "PluginHostHealth",
    "PluginHostIntegrityFinding",
    "PluginHostProcessRecord",
    "PluginHostResourcePolicy",
    "PluginReady",
    "utc_now",
]
