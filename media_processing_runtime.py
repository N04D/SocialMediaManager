from __future__ import annotations

import hashlib
from contextlib import contextmanager
from uuid import uuid4

from channel_store import now_iso
from media_store import (
    find_media_variant_by_key,
    get_media_variant,
    save_media_asset,
    save_media_variant,
)
from src.core.media import (
    ChannelMediaRequirements,
    ChannelMediaResolution,
    ImageInspectionResult,
    MediaInput,
    MediaMaterialization,
    MediaMaterializeOptions,
    MediaMimeTypeError,
    MediaRequirementViolation,
    MediaStatus,
    MediaStoreOptions,
    MediaValidationError,
    MediaVariant,
    MediaVariantNotFoundError,
    MediaVariantStatus,
    ResolvedMediaItem,
)
from src.core.media.inspection import ImageInspector


def deterministic_variant_key(asset_id: str, source_checksum: str, requirement: ChannelMediaRequirements) -> str:
    raw = "|".join(
        [
            asset_id,
            source_checksum,
            requirement.channel_plugin_id,
            requirement.capability,
            requirement.requirement_id,
            requirement.requirement_version,
            requirement.preferred_mime_type,
            ",".join(requirement.allowed_mime_types),
            str(requirement.max_width),
            str(requirement.max_height),
            str(requirement.max_file_size),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ChannelMediaRequirementRegistry:
    def __init__(self) -> None:
        self._requirements: dict[tuple[str, str], ChannelMediaRequirements] = {}

    def register(self, requirements: ChannelMediaRequirements) -> None:
        self._requirements[(requirements.channel_plugin_id, requirements.capability)] = requirements

    def get(self, channel_plugin_id: str, capability: str) -> ChannelMediaRequirements:
        requirement = self._requirements.get((channel_plugin_id, capability))
        if requirement is None:
            raise MediaValidationError(
                "media.requirement_not_registered",
                "No media requirements are registered for this channel capability.",
                {"channel_plugin_id": channel_plugin_id, "capability": capability},
            )
        return requirement

    def list(self) -> list[ChannelMediaRequirements]:
        return [self._requirements[key] for key in sorted(self._requirements)]


class BasicImageProcessingPlugin:
    plugin_id = "media.image.processing.basic"

    def __init__(self, *, inspector: ImageInspector | None = None) -> None:
        self.inspector = inspector or ImageInspector()

    def health_check(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "status": "ready",
            "capabilities": ["media.image.inspect", "media.image.processing.basic"],
            "supported_mime_types": ["image/jpeg", "image/png"],
        }

    def inspect(self, data: bytes, *, mime_type: str) -> ImageInspectionResult:
        return self.inspector.inspect_bytes(data, mime_type=mime_type)

    def create_variant_copy(
        self,
        *,
        app_runtime,
        asset,
        requirement: ChannelMediaRequirements,
        variant_key: str,
    ) -> MediaVariant:
        provider = app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        data = b"".join(provider.open_stream(asset.storage_reference))
        stored = provider.store(
            MediaInput(data=data, original_filename=asset.original_filename, declared_mime_type=asset.mime_type),
            MediaStoreOptions(
                workspace_id=asset.workspace_id,
                purpose=requirement.capability,
                allowed_mime_types=requirement.allowed_mime_types,
                metadata={"variant_key": variant_key, "source_asset_id": asset.id},
            ),
        )
        inspection = self.inspect(data, mime_type=stored.mime_type)
        current_time = now_iso()
        variant = MediaVariant(
            id=f"variant_{uuid4().hex}",
            asset_id=asset.id,
            workspace_id=asset.workspace_id,
            variant_key=variant_key,
            purpose=requirement.capability,
            media_type=asset.media_type,
            mime_type=stored.mime_type,
            storage_provider_id=stored.provider_id,
            storage_reference=stored.storage_reference,
            checksum=stored.checksum,
            source_checksum=asset.checksum,
            file_size=stored.file_size,
            width=inspection.width,
            height=inspection.height,
            generated_by_plugin_id=self.plugin_id,
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.requirement_version,
            transformation={"operation": "copy", "reason": "deterministic_channel_variant"},
            status=MediaVariantStatus.AVAILABLE.value
            if inspection.status == "passed"
            else MediaVariantStatus.FAILED.value,
            created_at=current_time,
            updated_at=current_time,
            metadata={"inspection": inspection.__dict__},
        )
        return save_media_variant(variant)


class MediaProcessingRuntime:
    def __init__(
        self,
        *,
        app_runtime,
        config,
        processor: BasicImageProcessingPlugin | None = None,
        requirement_registry: ChannelMediaRequirementRegistry | None = None,
    ) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.processor = processor or BasicImageProcessingPlugin()
        self.requirement_registry = requirement_registry or ChannelMediaRequirementRegistry()

    def health_check(self) -> dict:
        return {
            "status": "ready",
            "processor": self.processor.health_check(),
            "registered_requirements": [
                {
                    "channel_plugin_id": item.channel_plugin_id,
                    "capability": item.capability,
                    "requirement_version": item.requirement_version,
                }
                for item in self.requirement_registry.list()
            ],
        }

    def inspect_asset(self, asset_id: str, *, workspace_id: str = "") -> ImageInspectionResult:
        media_runtime = self.app_runtime.media_runtime(self.config)
        asset = media_runtime.get_asset(asset_id, workspace_id=workspace_id)
        provider = self.app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        data = b"".join(provider.open_stream(asset.storage_reference))
        inspection = self.processor.inspect(data, mime_type=asset.mime_type)
        metadata = dict(asset.metadata or {})
        metadata["image_inspection"] = {
            "mime_type": inspection.mime_type,
            "width": inspection.width,
            "height": inspection.height,
            "file_size": inspection.file_size,
            "checksum": inspection.checksum,
            "status": inspection.status,
            "inspector_id": inspection.inspector_id,
            "inspected_at": inspection.inspected_at,
            "errors": list(inspection.errors),
        }
        asset.metadata = metadata
        if inspection.status == "passed":
            asset.width = inspection.width
            asset.height = inspection.height
        asset.updated_at = now_iso()
        save_media_asset(asset)
        return inspection

    def resolve_channel_media(
        self,
        asset_ids: list[str],
        *,
        workspace_id: str,
        channel_plugin_id: str,
        capability: str,
        prefer_variant: bool = False,
    ) -> ChannelMediaResolution:
        requirement = self.requirement_registry.get(channel_plugin_id, capability)
        selected: list[ResolvedMediaItem] = []
        rejected: list[MediaRequirementViolation] = []
        warnings: list[str] = []
        media_runtime = self.app_runtime.media_runtime(self.config)
        for asset_id in asset_ids[: requirement.max_assets]:
            asset = media_runtime.get_asset(asset_id, workspace_id=workspace_id)
            violations = self._asset_violations(asset, requirement)
            if violations:
                rejected.extend(violations)
                continue
            if not asset.width or not asset.height:
                inspection = self.inspect_asset(asset.id, workspace_id=workspace_id)
                if inspection.status != "passed":
                    rejected.append(
                        MediaRequirementViolation(
                            code="media.inspection_failed",
                            message="Image inspection failed.",
                            asset_id=asset.id,
                        )
                    )
                    continue
                asset = media_runtime.get_asset(asset.id, workspace_id=workspace_id)
            direct_ok = not prefer_variant and self._direct_use_ok(asset, requirement)
            if direct_ok:
                selected.append(self._item_from_asset(asset, requirement))
                continue
            variant = self.ensure_variant(asset.id, workspace_id=workspace_id, requirement=requirement)
            variant_violations = self._variant_violations(variant, requirement)
            if variant_violations:
                rejected.extend(variant_violations)
                continue
            selected.append(self._item_from_variant(asset, variant, requirement))
        if len(asset_ids) > requirement.max_assets:
            warnings.append("media.max_assets_applied")
        return ChannelMediaResolution(
            channel_plugin_id=channel_plugin_id,
            capability=capability,
            selected=tuple(selected),
            rejected=tuple(rejected),
            warnings=tuple(warnings),
            requirement_version=requirement.requirement_version,
        )

    def ensure_variant(
        self,
        asset_id: str,
        *,
        workspace_id: str,
        requirement: ChannelMediaRequirements,
    ) -> MediaVariant:
        media_runtime = self.app_runtime.media_runtime(self.config)
        asset = media_runtime.get_asset(asset_id, workspace_id=workspace_id)
        key = deterministic_variant_key(asset.id, asset.checksum, requirement)
        existing = find_media_variant_by_key(asset.id, key)
        if existing is not None and existing.status == MediaVariantStatus.AVAILABLE.value:
            return existing
        pending = existing or MediaVariant(
            id=f"variant_{uuid4().hex}",
            asset_id=asset.id,
            workspace_id=asset.workspace_id,
            variant_key=key,
            purpose=requirement.capability,
            media_type=asset.media_type,
            mime_type=asset.mime_type,
            storage_provider_id=asset.storage_provider_id,
            storage_reference="",
            checksum="",
            source_checksum=asset.checksum,
            file_size=0,
            generated_by_plugin_id=self.processor.plugin_id,
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.requirement_version,
            status=MediaVariantStatus.PROCESSING.value,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        save_media_variant(pending)
        return self.processor.create_variant_copy(
            app_runtime=self.app_runtime,
            asset=asset,
            requirement=requirement,
            variant_key=key,
        )

    @contextmanager
    def materialize_resolved(self, item: ResolvedMediaItem, *, workspace_id: str, purpose: str):
        media_runtime = self.app_runtime.media_runtime(self.config)
        asset = media_runtime.get_asset(item.asset_id, workspace_id=workspace_id)
        if item.direct_use:
            with media_runtime.materialize(asset.id, workspace_id=workspace_id, purpose=purpose) as materialized:
                yield materialized
            return
        variant = get_media_variant(item.variant_id)
        if variant is None or variant.asset_id != asset.id:
            raise MediaVariantNotFoundError("media.variant_not_found", "Media variant was not found.")
        provider = self.app_runtime.media_provider(preferred_provider_id=variant.storage_provider_id)
        materialized = provider.materialize(
            variant.storage_reference,
            MediaMaterializeOptions(purpose=purpose, preferred_filename=asset.original_filename),
        )
        wrapped = MediaMaterialization(
            id=materialized.id,
            asset_id=asset.id,
            variant_id=variant.id,
            provider_id=materialized.provider_id,
            local_path=materialized.local_path,
            created_at=materialized.created_at,
            expires_at=materialized.expires_at,
            cleanup_required=materialized.cleanup_required,
            checksum=materialized.checksum,
            purpose=materialized.purpose,
        )
        try:
            yield wrapped
        finally:
            provider.cleanup_materialization(wrapped)

    def _asset_violations(self, asset, requirement: ChannelMediaRequirements) -> list[MediaRequirementViolation]:
        if asset.status != MediaStatus.AVAILABLE.value:
            return [
                MediaRequirementViolation(
                    code="media.asset_unavailable",
                    message="Media asset is not available.",
                    asset_id=asset.id,
                )
            ]
        if asset.mime_type not in requirement.allowed_mime_types:
            return [
                MediaRequirementViolation(
                    code="media.mime_not_allowed",
                    message="Media MIME type is not allowed.",
                    asset_id=asset.id,
                )
            ]
        if asset.file_size > requirement.max_file_size:
            return [
                MediaRequirementViolation(
                    code="media.file_too_large",
                    message="Media file is too large for this channel.",
                    asset_id=asset.id,
                )
            ]
        return []

    def _variant_violations(
        self, variant: MediaVariant, requirement: ChannelMediaRequirements
    ) -> list[MediaRequirementViolation]:
        if variant.status != MediaVariantStatus.AVAILABLE.value:
            return [
                MediaRequirementViolation(
                    code="media.variant_unavailable",
                    message="Media variant is not available.",
                    asset_id=variant.asset_id,
                    variant_id=variant.id,
                )
            ]
        if variant.mime_type not in requirement.allowed_mime_types:
            raise MediaMimeTypeError("media.variant_mime_not_allowed", "Media variant MIME type is not allowed.")
        if variant.file_size > requirement.max_file_size:
            return [
                MediaRequirementViolation(
                    code="media.variant_file_too_large",
                    message="Media variant is too large for this channel.",
                    asset_id=variant.asset_id,
                    variant_id=variant.id,
                )
            ]
        if not self._dimensions_ok(variant.width, variant.height, requirement):
            return [
                MediaRequirementViolation(
                    code="media.variant_dimensions_invalid",
                    message="Media variant dimensions are not valid for this channel.",
                    asset_id=variant.asset_id,
                    variant_id=variant.id,
                )
            ]
        return []

    def _direct_use_ok(self, asset, requirement: ChannelMediaRequirements) -> bool:
        if requirement.preferred_mime_type and asset.mime_type != requirement.preferred_mime_type:
            return False
        return self._dimensions_ok(asset.width, asset.height, requirement)

    @staticmethod
    def _dimensions_ok(width: int, height: int, requirement: ChannelMediaRequirements) -> bool:
        return (
            requirement.min_width <= width <= requirement.max_width
            and requirement.min_height <= height <= requirement.max_height
        )

    @staticmethod
    def _item_from_asset(asset, requirement: ChannelMediaRequirements) -> ResolvedMediaItem:
        return ResolvedMediaItem(
            asset_id=asset.id,
            variant_id="",
            media_type=asset.media_type,
            mime_type=asset.mime_type,
            file_size=asset.file_size,
            checksum=asset.checksum,
            width=asset.width,
            height=asset.height,
            direct_use=True,
            processor_plugin_id="",
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.requirement_version,
        )

    @staticmethod
    def _item_from_variant(asset, variant: MediaVariant, requirement: ChannelMediaRequirements) -> ResolvedMediaItem:
        return ResolvedMediaItem(
            asset_id=asset.id,
            variant_id=variant.id,
            media_type=variant.media_type,
            mime_type=variant.mime_type,
            file_size=variant.file_size,
            checksum=variant.checksum,
            width=variant.width,
            height=variant.height,
            direct_use=False,
            processor_plugin_id=variant.generated_by_plugin_id,
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.requirement_version,
        )
