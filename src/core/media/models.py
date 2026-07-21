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
