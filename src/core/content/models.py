from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ContentType(StrEnum):
    SOCIAL_POST = "social_post"
    ANNOUNCEMENT = "announcement"
    ARTICLE_SOURCE = "article_source"
    CAMPAIGN_MESSAGE = "campaign_message"
    NOTE = "note"
    UNKNOWN = "unknown"


class ContentCompleteness(StrEnum):
    METADATA_ONLY = "metadata_only"
    TRANSCRIPT_AVAILABLE = "transcript_available"
    PARTIAL = "partial"
    COMPLETE = "complete"


class ArtifactType(StrEnum):
    TRANSCRIPT_RAW = "transcript.raw"
    TRANSCRIPT_NORMALIZED = "transcript.normalized"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PLANNED = "planned"
    PARTIALLY_PUBLISHED = "partially_published"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ChannelContentVariantType(StrEnum):
    MANUAL = "manual"
    ADAPTED = "adapted"
    IMPORTED = "imported"
    LEGACY = "legacy"
    GENERATED_PLACEHOLDER = "generated_placeholder"


class ChannelContentVariantStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    STALE = "stale"
    INVALID = "invalid"
    ARCHIVED = "archived"


class PublicationPlanStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    SCHEDULED = "scheduled"
    PARTIALLY_QUEUED = "partially_queued"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class PublicationTargetStatus(StrEnum):
    DRAFT = "draft"
    INVALID = "invalid"
    READY = "ready"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    PUBLISHED = "published"
    UNCERTAIN = "uncertain"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


@dataclass
class ContentItem:
    id: str
    workspace_id: str
    content_type: str
    title: str
    body: str
    summary: str = ""
    language: str = ""
    status: str = ContentStatus.DRAFT.value
    current_revision_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    source_type: str = ""
    source_reference: str = ""
    primary_source_type: str = ""
    primary_source_entity_id: str = ""
    primary_source_ref: str = ""
    primary_source_metadata: dict[str, Any] = field(default_factory=dict)
    canonical_text_representation: str = ""
    canonical_media_refs: list[str] = field(default_factory=list)
    canonical_metadata: dict[str, Any] = field(default_factory=dict)
    source_provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentRevision:
    id: str
    content_item_id: str
    workspace_id: str
    revision_number: int
    title: str
    body: str
    summary: str = ""
    language: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    primary_source_type: str = ""
    primary_source_entity_id: str = ""
    primary_source_ref: str = ""
    canonical_representation_id: str = ""
    canonical_text_representation: str = ""
    source_provenance: dict[str, Any] = field(default_factory=dict)
    relationship_ids: list[str] = field(default_factory=list)
    checksum: str = ""
    created_at: str = ""
    created_by: str = ""
    change_reason: str = ""


@dataclass
class Artifact:
    artifact_id: str
    content_entity_id: str
    revision_id: str
    artifact_type: str
    media_type: str
    source: str
    language: str
    content_hash: str
    storage_ref: str
    created_at: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelContentVariant:
    id: str
    workspace_id: str
    content_item_id: str
    source_revision_id: str
    channel_plugin_id: str
    capability: str
    variant_type: str
    title: str
    body: str
    summary: str = ""
    hashtags: list[str] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    call_to_action: str = ""
    language: str = ""
    status: str = ChannelContentVariantStatus.DRAFT.value
    validation_status: str = "unknown"
    requirement_version: str = ""
    variant_checksum: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    primary_source_type: str = ""
    primary_source_entity_id: str = ""
    primary_source_ref: str = ""
    campaign_id: str = ""
    intent_id: str = ""
    transformation_run_id: str = ""
    source_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelContentRequirements:
    channel_plugin_id: str
    capability: str
    version: str
    title_supported: bool
    title_required: bool
    body_required: bool
    min_body_length: int = 0
    max_body_length: int = 0
    max_title_length: int = 0
    supported_languages: tuple[str, ...] = field(default_factory=tuple)
    hashtags_supported: bool = False
    max_hashtags: int = 0
    mentions_supported: bool = False
    links_supported: bool = True
    line_breaks_supported: bool = True
    media_required: bool = False
    maximum_media_items: int = 0
    variant_required: bool = False
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentRequirementViolation:
    code: str
    message: str
    field: str = ""


@dataclass(frozen=True)
class ContentRequirementResult:
    suitable: bool
    direct_use: bool
    variant_required: bool
    violations: tuple[ContentRequirementViolation, ...] = field(default_factory=tuple)
    warnings: tuple[ContentRequirementViolation, ...] = field(default_factory=tuple)
    requirement_version: str = ""
    selected_revision_id: str = ""
    selected_variant_id: str = ""


@dataclass
class PublicationPlan:
    id: str
    workspace_id: str
    content_item_id: str
    source_revision_id: str
    name: str
    status: str = PublicationPlanStatus.DRAFT.value
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    planned_start_at: str = ""
    timezone: str = "UTC"
    notes: str = ""
    validation_status: str = "unknown"
    snapshot_checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublicationTarget:
    id: str
    publication_plan_id: str
    workspace_id: str
    channel_plugin_id: str
    channel_account_id: str
    capability: str
    source_revision_id: str
    channel_variant_id: str = ""
    media_relation_ids: list[str] = field(default_factory=list)
    position: int = 0
    scheduled_at: str = ""
    timezone: str = "UTC"
    status: str = PublicationTargetStatus.DRAFT.value
    validation_status: str = "unknown"
    snapshot_checksum: str = ""
    job_id: str = ""
    publication_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentAuditEvent:
    id: str
    workspace_id: str
    action: str
    target_id: str
    target_type: str
    actor: str = ""
    reason: str = ""
    result: str = "ok"
    safe_error_code: str = ""
    snapshot_checksum: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentIntegrityIssue:
    code: str
    message: str
    count: int = 1
    examples: tuple[dict[str, str], ...] = field(default_factory=tuple)
