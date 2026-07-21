"""Public channel plugin interfaces and models for Plugin SDK v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .errors import PluginCapabilityUnsupportedError


@dataclass(frozen=True)
class ResolvedContent:
    """Immutable content selected by the application layer for a channel publish."""

    content_item_id: str
    revision_id: str
    revision_checksum: str
    variant_id: str = ""
    variant_checksum: str = ""
    title: str = ""
    body: str = ""
    summary: str = ""
    language: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMediaItem:
    """Media selected for a publish without exposing storage references."""

    relation_id: str
    asset_id: str
    variant_id: str
    mime_type: str
    checksum: str
    position: int
    role: str = "attachment"
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelPublishRequest:
    """Stable application-to-channel publish request."""

    workspace_id: str
    channel_account_id: str
    publication_id: str
    publication_plan_id: str
    publication_target_id: str
    execution_attempt_id: str
    execution_generation: int
    snapshot_checksum: str
    capability: str
    resolved_content: ResolvedContent
    resolved_media: tuple[ResolvedMediaItem, ...] = field(default_factory=tuple)
    channel_options: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    scheduled_intent: dict[str, Any] = field(default_factory=dict)
    confirmation_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelPublishResult:
    """Stable channel-to-application publish result."""

    status: str
    publication_id: str
    remote_publication_id: str = ""
    remote_uri: str = ""
    remote_url: str = ""
    published_at: datetime | None = None
    verified_at: datetime | None = None
    mutation_state: str = "unknown"
    verification_state: str = "unverified"
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""

    def __post_init__(self) -> None:
        if self.status == "published" and not (self.remote_uri and self.verified_at):
            raise ValueError("published results require remote_uri and verified_at")


@dataclass(frozen=True)
class ChannelConnectRequest:
    workspace_id: str
    actor_id: str = ""
    channel_account_id: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    redirect_uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelConnectCallbackRequest:
    workspace_id: str
    channel_account_id: str
    query: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelDisconnectRequest:
    workspace_id: str
    channel_account_id: str
    actor_id: str = ""
    force: bool = False


@dataclass(frozen=True)
class ChannelStatusRequest:
    workspace_id: str
    channel_account_id: str


@dataclass(frozen=True)
class ChannelSessionCheckRequest:
    workspace_id: str
    channel_account_id: str


@dataclass(frozen=True)
class ChannelMetricsRequest:
    workspace_id: str
    channel_account_id: str
    publication_id: str
    remote_publication_id: str = ""
    remote_uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelHealthRequest:
    workspace_id: str = ""
    channel_account_id: str = ""
    include_remote_checks: bool = False


@dataclass(frozen=True)
class ChannelAccountIdentity:
    provider_key: str
    remote_account_id: str = ""
    display_name: str = ""
    profile_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelConnectResult:
    status: str
    next_action: str = "none"
    redirect_url: str = ""
    takeover_reference: str = ""
    expires_at: datetime | None = None
    account_identity: ChannelAccountIdentity | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""


@dataclass(frozen=True)
class ChannelDisconnectResult:
    status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""


@dataclass(frozen=True)
class ChannelAccountStatus:
    status: str
    account_identity: ChannelAccountIdentity | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""


@dataclass(frozen=True)
class ChannelSessionCheckResult:
    status: str
    account_identity: ChannelAccountIdentity | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""


@dataclass(frozen=True)
class ChannelMetricsResult:
    status: str
    observations: tuple[Any, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_error_code: str = ""


@dataclass(frozen=True)
class ChannelHealth:
    status: str
    plugin_id: str
    checked_at: datetime | None = None
    capabilities: dict[str, str] = field(default_factory=dict)
    contract_versions: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelRuntime(Protocol):
    """Public async runtime interface implemented by channel plugins."""

    async def start_connect(self, request: ChannelConnectRequest) -> ChannelConnectResult: ...
    async def complete_connect(self, request: ChannelConnectCallbackRequest) -> ChannelConnectResult: ...
    async def disconnect(self, request: ChannelDisconnectRequest) -> ChannelDisconnectResult: ...
    async def get_status(self, request: ChannelStatusRequest) -> ChannelAccountStatus: ...
    async def check_session(self, request: ChannelSessionCheckRequest) -> ChannelSessionCheckResult: ...
    async def publish(self, request: ChannelPublishRequest) -> ChannelPublishResult: ...
    async def collect_metrics(self, request: ChannelMetricsRequest) -> ChannelMetricsResult: ...
    async def health_check(self, request: ChannelHealthRequest) -> ChannelHealth: ...


class ChannelRuntimeBase:
    """Convenience base returning standardized unsupported-capability errors."""

    plugin_id = "channel.unknown"

    def _unsupported(self, capability: str) -> PluginCapabilityUnsupportedError:
        return PluginCapabilityUnsupportedError(
            "plugin_sdk.capability_unsupported",
            f"{self.plugin_id} does not support {capability}.",
            {"plugin_id": self.plugin_id, "capability": capability},
        )

    async def start_connect(self, request: ChannelConnectRequest) -> ChannelConnectResult:
        raise self._unsupported("channel.connect")

    async def complete_connect(self, request: ChannelConnectCallbackRequest) -> ChannelConnectResult:
        raise self._unsupported("channel.connect")

    async def disconnect(self, request: ChannelDisconnectRequest) -> ChannelDisconnectResult:
        raise self._unsupported("channel.disconnect")

    async def get_status(self, request: ChannelStatusRequest) -> ChannelAccountStatus:
        raise self._unsupported("channel.status")

    async def check_session(self, request: ChannelSessionCheckRequest) -> ChannelSessionCheckResult:
        raise self._unsupported("channel.status")

    async def publish(self, request: ChannelPublishRequest) -> ChannelPublishResult:
        raise self._unsupported(request.capability)

    async def collect_metrics(self, request: ChannelMetricsRequest) -> ChannelMetricsResult:
        raise self._unsupported("channel.metrics.collect")

    async def health_check(self, request: ChannelHealthRequest) -> ChannelHealth:
        raise self._unsupported("channel.health")


@dataclass
class PluginRegistrationContext:
    """Controlled registration surface for SDK-compatible plugins."""

    plugin_id: str
    capabilities: set[str] = field(default_factory=set)
    runtime_factories: dict[str, Any] = field(default_factory=dict)
    requirement_resolvers: dict[str, Any] = field(default_factory=dict)
    metric_definitions: dict[str, Any] = field(default_factory=dict)
    health_providers: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def register_runtime_factory(self, plugin_id: str, factory: Any) -> None:
        if plugin_id in self.runtime_factories and self.runtime_factories[plugin_id] is not factory:
            raise PluginCapabilityUnsupportedError(
                "plugin_sdk.duplicate_runtime", "Runtime factory already registered."
            )
        self.runtime_factories[plugin_id] = factory

    def register_requirements(self, key: str, resolver: Any) -> None:
        if key in self.requirement_resolvers:
            raise PluginCapabilityUnsupportedError(
                "plugin_sdk.duplicate_requirements", "Requirements already registered."
            )
        self.requirement_resolvers[key] = resolver

    def register_metric_definition(self, key: str, definition: Any) -> None:
        if key in self.metric_definitions:
            raise PluginCapabilityUnsupportedError(
                "plugin_sdk.duplicate_metric", "Metric definition already registered."
            )
        self.metric_definitions[key] = definition

    def publish_event(self, event_type: str, metadata: dict[str, Any] | None = None) -> None:
        self.events.append({"type": event_type, "metadata": metadata or {}})


@dataclass(frozen=True)
class ChannelRuntimeContext:
    """Least-privilege runtime context assembled by the application."""

    plugin_id: str
    workspace_id: str
    content: Any = None
    media: Any = None
    media_processing: Any = None
    execution: Any = None
    analytics: Any = None
    secrets: Any = None
    events: Any = None
    audit: Any = None
    clock: Any = None
    http_client_factory: Any = None
    browser_resolver: Any = None
    configuration: dict[str, Any] = field(default_factory=dict)
    permissions: frozenset[str] = field(default_factory=frozenset)

    def require_permission(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PluginCapabilityUnsupportedError(
                "plugin_sdk.permission_unavailable",
                f"Runtime context does not provide {permission}.",
                {"plugin_id": self.plugin_id, "permission": permission},
            )


class ChannelPlugin(Protocol):
    """Public plugin object loaded by PluginRuntime."""

    @property
    def manifest(self) -> Any: ...
    def register(self, context: PluginRegistrationContext) -> None: ...
    def create_runtime(self, context: ChannelRuntimeContext) -> ChannelRuntime: ...


__all__ = [
    "ChannelAccountIdentity",
    "ChannelAccountStatus",
    "ChannelConnectCallbackRequest",
    "ChannelConnectRequest",
    "ChannelConnectResult",
    "ChannelDisconnectRequest",
    "ChannelDisconnectResult",
    "ChannelHealth",
    "ChannelHealthRequest",
    "ChannelMetricsRequest",
    "ChannelMetricsResult",
    "ChannelPlugin",
    "ChannelPublishRequest",
    "ChannelPublishResult",
    "ChannelRuntime",
    "ChannelRuntimeBase",
    "ChannelRuntimeContext",
    "ChannelSessionCheckRequest",
    "ChannelSessionCheckResult",
    "ChannelStatusRequest",
    "PluginRegistrationContext",
    "ResolvedContent",
    "ResolvedMediaItem",
]
