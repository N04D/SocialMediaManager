from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from channel_store import now_iso, save_derivative
from media_store import (
    find_media_asset_by_checksum,
    get_legacy_media_mapping,
    get_media_asset,
    list_media_assets,
    save_legacy_media_mapping,
    save_media_asset,
)
from src.core.media import (
    MediaAccessMode,
    MediaAsset,
    MediaDeleteOptions,
    MediaInput,
    MediaMaterialization,
    MediaMaterializeOptions,
    MediaNotFoundError,
    MediaOwnershipError,
    MediaReference,
    MediaSourceType,
    MediaStatus,
    MediaStoreOptions,
    media_type_for_mime,
)
from src.core.media.errors import MediaUnsafePathError
from src.core.media.inspection import ImageInspector
from src.core.media.utils import safe_display_name


class MediaRuntime:
    def __init__(self, *, app_runtime, config) -> None:
        self.app_runtime = app_runtime
        self.config = config

    def storage_provider(self, *, preferred_provider_id: str = ""):
        return self.app_runtime.media_provider(preferred_provider_id=preferred_provider_id)

    def import_asset(
        self,
        *,
        workspace_id: str,
        source: MediaInput,
        storage_provider_id: str = "",
        created_by: str = "",
        metadata: dict | None = None,
        reuse_existing: bool = False,
    ) -> MediaAsset:
        provider = self.storage_provider(preferred_provider_id=storage_provider_id)
        stored = provider.store(
            source,
            MediaStoreOptions(
                workspace_id=workspace_id,
                purpose="media.import",
                metadata=metadata or {},
            ),
        )
        existing = find_media_asset_by_checksum(workspace_id, stored.checksum)
        if existing is not None and reuse_existing:
            provider.delete(stored.storage_reference, MediaDeleteOptions(reason="duplicate import cleanup"))
            return existing
        current_time = now_iso()
        inspection_metadata = {}
        width = 0
        height = 0
        if stored.mime_type in {"image/jpeg", "image/png"}:
            provider_data = b"".join(provider.open_stream(stored.storage_reference))
            inspection = ImageInspector().inspect_bytes(provider_data, mime_type=stored.mime_type)
            inspection_metadata = {
                "image_inspection": {
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
            }
            if inspection.status == "passed":
                width = inspection.width
                height = inspection.height
        asset = MediaAsset(
            id=f"media_{uuid4().hex}",
            workspace_id=workspace_id,
            media_type=media_type_for_mime(stored.mime_type),
            mime_type=stored.mime_type,
            original_filename=safe_display_name(source.original_filename),
            display_name=safe_display_name(source.original_filename),
            storage_provider_id=stored.provider_id,
            storage_reference=stored.storage_reference,
            checksum_algorithm="sha256",
            checksum=stored.checksum,
            file_size=stored.file_size,
            width=width,
            height=height,
            status=MediaStatus.AVAILABLE.value,
            created_at=current_time,
            updated_at=current_time,
            created_by=created_by,
            source_type=source.source_type,
            source_reference=source.source_reference,
            metadata=dict(metadata or {}) | {"provider_metadata": stored.provider_metadata} | inspection_metadata,
        )
        try:
            return save_media_asset(asset)
        except Exception:
            provider.delete(stored.storage_reference, MediaDeleteOptions(reason="repository failure cleanup"))
            raise

    def get_asset(self, asset_id: str, *, workspace_id: str = "") -> MediaAsset:
        asset = get_media_asset(asset_id)
        if asset is None or asset.status == MediaStatus.DELETED.value:
            raise MediaNotFoundError("media.asset_not_found", "Media asset was not found.")
        if workspace_id and asset.workspace_id != workspace_id:
            raise MediaOwnershipError("media.workspace_mismatch", "Media asset does not belong to this workspace.")
        return asset

    def list_assets(self, *, workspace_id: str = "") -> list[MediaAsset]:
        return list_media_assets(workspace_id=workspace_id)

    def resolve_reference(self, asset_id: str, *, workspace_id: str = "") -> MediaReference:
        asset = self.get_asset(asset_id, workspace_id=workspace_id)
        return MediaReference(
            asset_id=asset.id,
            variant_id="",
            provider_id=asset.storage_provider_id,
            media_type=asset.media_type,
            mime_type=asset.mime_type,
            file_size=asset.file_size,
            checksum=asset.checksum,
            access_mode=MediaAccessMode.DIRECT_REFERENCE.value,
            reference=f"media-asset:{asset.id}",
        )

    @contextmanager
    def materialize(self, asset_id: str, *, workspace_id: str, purpose: str):
        asset = self.get_asset(asset_id, workspace_id=workspace_id)
        provider = self.storage_provider(preferred_provider_id=asset.storage_provider_id)
        materialization = provider.materialize(
            asset.storage_reference,
            MediaMaterializeOptions(purpose=purpose, preferred_filename=asset.original_filename),
        )
        materialization = MediaMaterialization(
            id=materialization.id,
            asset_id=asset.id,
            variant_id="",
            provider_id=materialization.provider_id,
            local_path=materialization.local_path,
            created_at=materialization.created_at,
            expires_at=materialization.expires_at,
            cleanup_required=materialization.cleanup_required,
            checksum=materialization.checksum,
            purpose=materialization.purpose,
        )
        try:
            yield materialization
        finally:
            provider.cleanup_materialization(materialization)

    def soft_delete_asset(self, asset_id: str, *, workspace_id: str, actor: str, reason: str) -> MediaAsset:
        asset = self.get_asset(asset_id, workspace_id=workspace_id)
        asset.status = MediaStatus.DELETED.value
        asset.deleted_at = now_iso()
        asset.deleted_by = actor
        asset.delete_reason = reason
        asset.updated_at = asset.deleted_at
        return save_media_asset(asset)

    def import_legacy_path(self, path: Path, *, workspace_id: str, derivative=None) -> MediaAsset:
        safe_path = self._validate_legacy_path(path)
        mapped_id = get_legacy_media_mapping(safe_path)
        if mapped_id:
            return self.get_asset(mapped_id, workspace_id=workspace_id)
        asset = self.import_asset(
            workspace_id=workspace_id,
            source=MediaInput(
                local_path=safe_path,
                original_filename=safe_path.name,
                source_type=MediaSourceType.MIGRATION.value,
                source_reference="legacy_path",
            ),
            created_by="legacy_path_resolver",
            metadata={"legacy_path_import": True},
        )
        save_legacy_media_mapping(safe_path, asset.id)
        if derivative is not None:
            metadata = dict(derivative.generation_metadata_json or {})
            ids = list(metadata.get("media_asset_ids") or [])
            if asset.id not in ids:
                ids.append(asset.id)
            metadata["media_asset_ids"] = ids
            derivative.generation_metadata_json = metadata
            save_derivative(derivative)
        return asset

    def _validate_legacy_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        allowed_roots = [
            Path(getattr(self.config, "media_dir", ".")).expanduser().resolve(),
            Path(getattr(self.config, "content_dir", ".")).expanduser().resolve(),
        ]
        if not resolved.is_file() or resolved.is_symlink():
            raise MediaUnsafePathError("media.legacy_path_unsafe", "Legacy media path is not safe to import.")
        if not any(root == resolved or root in resolved.parents for root in allowed_roots):
            raise MediaUnsafePathError(
                "media.legacy_path_outside_allowed_roots",
                "Legacy media path is outside allowed roots.",
            )
        return resolved
