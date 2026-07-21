from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


class MediaStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    PROCESSING = "processing"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    DELETED = "deleted"
    QUARANTINED = "quarantined"


class MediaSourceType(StrEnum):
    UPLOAD = "upload"
    LOCAL_IMPORT = "local_import"
    GENERATED = "generated"
    CHANNEL_IMPORT = "channel_import"
    MIGRATION = "migration"
    UNKNOWN = "unknown"


class MediaAccessMode(StrEnum):
    STREAM = "stream"
    TEMPORARY_FILE = "temporary_file"
    DIRECT_REFERENCE = "direct_reference"


class MediaVariantStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETED = "deleted"


class ContentMediaOwnerType(StrEnum):
    CONTENT = "content"
    DRAFT = "draft"
    PUBLICATION = "publication"
    PUBLICATION_ATTEMPT = "publication_attempt"
    UNKNOWN = "unknown"


class ContentMediaRole(StrEnum):
    PRIMARY = "primary"
    SOCIAL_IMAGE = "social_image"
    ATTACHMENT = "attachment"
    GALLERY = "gallery"
    PUBLICATION_MEDIA = "publication_media"
    SOURCE = "source"
    REFERENCE = "reference"


class MediaUsageType(StrEnum):
    LINKED = "linked"
    SELECTED = "selected"
    MATERIALIZED = "materialized"
    PROCESSED = "processed"
    PUBLISH_ATTEMPT = "publish_attempt"
    PUBLISHED = "published"
    PREVIEWED = "previewed"


class MediaRetentionTargetType(StrEnum):
    VARIANT = "variant"
    SOFT_DELETED_ASSET = "soft_deleted_asset"
    TEMPORARY_MATERIALIZATION = "temporary_materialization"
    FAILED_PROCESSING_OUTPUT = "failed_processing_output"


class MediaRetentionPlanStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MediaAsset:
    id: str
    workspace_id: str
    media_type: str
    mime_type: str
    original_filename: str
    display_name: str
    storage_provider_id: str
    storage_reference: str
    checksum_algorithm: str
    checksum: str
    file_size: int
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    status: str = MediaStatus.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    source_type: str = MediaSourceType.UNKNOWN.value
    source_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    deleted_at: str = ""
    deleted_by: str = ""
    delete_reason: str = ""
    retention_pinned: bool = False
    pinned_at: str = ""
    pinned_by: str = ""
    pin_reason: str = ""


@dataclass
class MediaVariant:
    id: str
    asset_id: str
    purpose: str
    media_type: str
    mime_type: str
    storage_provider_id: str
    storage_reference: str
    checksum: str
    file_size: int
    workspace_id: str = ""
    variant_key: str = ""
    source_checksum: str = ""
    requirement_id: str = ""
    requirement_version: str = ""
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    generated_by_plugin_id: str = ""
    transformation: dict[str, Any] = field(default_factory=dict)
    status: str = MediaVariantStatus.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    retention_pinned: bool = False
    pinned_at: str = ""
    pinned_by: str = ""
    pin_reason: str = ""


@dataclass(frozen=True)
class MediaReference:
    asset_id: str
    variant_id: str
    provider_id: str
    media_type: str
    mime_type: str
    file_size: int
    checksum: str
    access_mode: str
    reference: str
    expires_at: str = ""


@dataclass(frozen=True)
class MediaMaterialization:
    id: str
    asset_id: str
    variant_id: str
    provider_id: str
    local_path: Path
    created_at: str
    expires_at: str
    cleanup_required: bool
    checksum: str
    purpose: str


@dataclass
class MediaInput:
    data: bytes | None = None
    stream: BinaryIO | None = None
    local_path: Path | None = None
    original_filename: str = ""
    declared_mime_type: str = ""
    expected_size: int = 0
    expected_checksum: str = ""
    source_type: str = MediaSourceType.UNKNOWN.value
    source_reference: str = ""


@dataclass(frozen=True)
class MediaStoreOptions:
    workspace_id: str
    purpose: str = ""
    idempotency_key: str = ""
    maximum_size: int = 25_000_000
    allowed_mime_types: tuple[str, ...] = ("image/jpeg", "image/png")
    preserve_original_filename: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredMedia:
    storage_reference: str
    provider_id: str
    file_size: int
    mime_type: str
    checksum: str
    stored_at: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaObjectMetadata:
    file_size: int
    mime_type: str
    checksum: str
    created_at: str
    updated_at: str
    exists: bool
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaMaterializeOptions:
    purpose: str
    expires_in: int = 900
    preferred_filename: str = ""
    read_only: bool = True
    verify_checksum: bool = True


@dataclass(frozen=True)
class MediaDeleteOptions:
    reason: str
    actor: str = ""
    physical: bool = False


@dataclass(frozen=True)
class ImageInspectionResult:
    mime_type: str
    width: int
    height: int
    file_size: int
    checksum: str
    status: str
    inspector_id: str
    inspected_at: str
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChannelMediaRequirements:
    channel_plugin_id: str
    capability: str
    requirement_id: str
    requirement_version: str
    media_type: str = MediaType.IMAGE.value
    allowed_mime_types: tuple[str, ...] = ("image/jpeg", "image/png")
    min_width: int = 1
    min_height: int = 1
    max_width: int = 7680
    max_height: int = 4320
    max_file_size: int = 25_000_000
    max_assets: int = 9
    preferred_mime_type: str = ""
    processor_plugin_id: str = "media.image.processing.basic"


@dataclass(frozen=True)
class MediaRequirementViolation:
    code: str
    message: str
    asset_id: str = ""
    variant_id: str = ""


@dataclass(frozen=True)
class ResolvedMediaItem:
    asset_id: str
    variant_id: str
    media_type: str
    mime_type: str
    file_size: int
    checksum: str
    width: int
    height: int
    direct_use: bool
    processor_plugin_id: str
    requirement_id: str
    requirement_version: str


@dataclass(frozen=True)
class ChannelMediaResolution:
    channel_plugin_id: str
    capability: str
    selected: tuple[ResolvedMediaItem, ...] = field(default_factory=tuple)
    rejected: tuple[MediaRequirementViolation, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    requirement_version: str = ""


@dataclass
class ContentMediaRelation:
    id: str
    workspace_id: str
    owner_type: str
    owner_id: str
    asset_id: str
    variant_id: str = ""
    role: str = ContentMediaRole.ATTACHMENT.value
    position: int = 0
    channel_plugin_id: str = ""
    publication_id: str = ""
    required: bool = False
    active: bool = True
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaUsage:
    id: str
    workspace_id: str
    asset_id: str
    variant_id: str = ""
    usage_type: str = MediaUsageType.LINKED.value
    owner_type: str = ContentMediaOwnerType.UNKNOWN.value
    owner_id: str = ""
    channel_plugin_id: str = ""
    publication_id: str = ""
    job_id: str = ""
    status: str = "active"
    first_used_at: str = ""
    last_used_at: str = ""
    usage_count: int = 0
    retained_until: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectedMediaItem:
    relation_id: str
    asset_id: str
    variant_id: str
    role: str
    position: int
    resolved_mime_type: str
    width: int
    height: int
    checksum: str
    direct_use: bool
    processor_plugin_id: str
    suitability_status: str


@dataclass(frozen=True)
class MediaSelectionResult:
    owner_type: str
    owner_id: str
    channel_plugin_id: str
    capability: str
    selected_items: tuple[SelectedMediaItem, ...] = field(default_factory=tuple)
    rejected_items: tuple[MediaRequirementViolation, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    requirement_version: str = ""


@dataclass
class MediaRetentionPolicy:
    id: str
    workspace_id: str
    target_type: str = MediaRetentionTargetType.VARIANT.value
    unused_for_days: int = 30
    failed_variant_days: int = 7
    deleted_asset_days: int = 30
    keep_historical_publications: bool = True
    keep_latest_variants_per_spec: int = 1
    dry_run_required: bool = True
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class MediaRetentionCandidate:
    asset_id: str
    variant_id: str
    status: str
    reason: str
    last_used_at: str
    relation_count: int
    publication_usage_count: int
    estimated_bytes: int
    blockers: tuple[str, ...] = field(default_factory=tuple)
    proposed_action: str = "variant_soft_delete"


@dataclass
class MediaRetentionPlan:
    id: str
    workspace_id: str
    policy_id: str
    created_at: str
    created_by: str
    reason: str
    status: str = MediaRetentionPlanStatus.DRAFT.value
    candidate_count: int = 0
    estimated_bytes: int = 0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    confirmation_required: bool = True
    confirmation_token: str = ""
    updated_at: str = ""


@dataclass
class MediaAuditEvent:
    id: str
    workspace_id: str
    action: str
    target_type: str
    target_id: str
    actor: str
    created_at: str
    reason: str = ""
    result: str = "success"
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaIntegrityIssue:
    code: str
    severity: str
    message: str
    identifiers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaLibrarySearchResult:
    assets: tuple[dict[str, Any], ...]
    page: int
    page_size: int
    total: int
    has_next: bool
