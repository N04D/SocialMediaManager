from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from src.core.media import (
    MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION,
    MediaDeleteOptions,
    MediaInput,
    MediaMaterialization,
    MediaMaterializeOptions,
    MediaNotFoundError,
    MediaObjectMetadata,
    MediaStorageConfigurationError,
    MediaStorageError,
    MediaStoreOptions,
    MediaUnsafePathError,
    StoredMedia,
    media_contract_payload,
)
from src.core.media.utils import guess_mime_type, read_media_input, safe_extension_for_mime, sha256_bytes, validate_mime

PROVIDER_ID = "provider.media.storage.local"


@dataclass(frozen=True)
class LocalMediaStorageConfig:
    root: Path
    max_size: int = 25_000_000

    @classmethod
    def from_app_config(cls, config) -> LocalMediaStorageConfig:
        return cls(root=Path(getattr(config, "media_storage_root", "./studio_data/media")))


class LocalMediaStorageProvider:
    provider_id = PROVIDER_ID

    def __init__(self, config=None, *, storage_config: LocalMediaStorageConfig | None = None) -> None:
        self.config = storage_config or LocalMediaStorageConfig.from_app_config(config)
        self.root = self._safe_root(self.config.root)
        self.objects_dir = self.root / "objects"
        self.materialized_dir = self.root / "materialized"
        self.quarantine_dir = self.root / "quarantine"
        self.metadata_dir = self.root / "metadata"

    def health_check(self) -> dict:
        messages: list[str] = []
        try:
            self._ensure_dirs()
            probe = self.root / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            messages.append(f"Local media storage is not writable: {exc.__class__.__name__}")
        return {
            "provider_id": self.provider_id,
            "status": "ready" if not messages else "error",
            "ok": not messages,
            "storage_type": "local",
            "configured": True,
            "readable": os.access(self.root, os.R_OK) if self.root.exists() else False,
            "writable": os.access(self.root, os.W_OK) if self.root.exists() else False,
            "materialization_available": not messages,
            "capabilities": [
                "media.storage",
                "media.storage.store",
                "media.storage.read",
                "media.storage.materialize",
                "media.storage.delete",
            ],
            "messages": messages,
            **media_contract_payload(implemented_storage_version=MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION),
        }

    def store(self, source: MediaInput, options: MediaStoreOptions) -> StoredMedia:
        self._ensure_dirs()
        mime_type, mime_status = guess_mime_type(source)
        validate_mime(mime_type, options.allowed_mime_types)
        data = read_media_input(source, maximum_size=min(options.maximum_size, self.config.max_size))
        checksum = sha256_bytes(data)
        object_id = uuid4().hex
        reference = f"local-object:{object_id}"
        target = self._object_path(reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial")
        try:
            with partial.open("xb") as handle:
                handle.write(data)
            os.chmod(partial, 0o600)
            if sha256_bytes(partial.read_bytes()) != checksum:
                raise MediaStorageError("media.write_checksum_mismatch", "Media write checksum did not verify.")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return StoredMedia(
            storage_reference=reference,
            provider_id=self.provider_id,
            file_size=len(data),
            mime_type=mime_type,
            checksum=checksum,
            stored_at="local",
            provider_metadata={"mime_status": mime_status},
        )

    def exists(self, storage_reference: str) -> bool:
        try:
            return self._object_path(storage_reference).is_file()
        except MediaUnsafePathError:
            return False

    def stat(self, storage_reference: str) -> MediaObjectMetadata:
        path = self._object_path(storage_reference)
        if not path.is_file():
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        data = path.read_bytes()
        return MediaObjectMetadata(
            file_size=len(data),
            mime_type="application/octet-stream",
            checksum=sha256_bytes(data),
            created_at="",
            updated_at="",
            exists=True,
        )

    def open_stream(self, storage_reference: str):
        path = self._object_path(storage_reference)
        if not path.is_file():
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    def materialize(self, storage_reference: str, options: MediaMaterializeOptions) -> MediaMaterialization:
        self._ensure_dirs()
        source = self._object_path(storage_reference)
        if not source.is_file():
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        data = source.read_bytes()
        suffix = safe_extension_for_mime("image/png" if options.preferred_filename.endswith(".png") else "image/jpeg")
        target = self.materialized_dir / f"{uuid4().hex}{suffix}"
        shutil.copyfile(source, target)
        os.chmod(target, 0o400 if options.read_only else 0o600)
        return MediaMaterialization(
            id=f"mat_{uuid4().hex}",
            asset_id="",
            variant_id="",
            provider_id=self.provider_id,
            local_path=target,
            created_at="local",
            expires_at="",
            cleanup_required=True,
            checksum=sha256_bytes(data),
            purpose=options.purpose,
        )

    def cleanup_materialization(self, materialization: MediaMaterialization) -> None:
        materialization.local_path.unlink(missing_ok=True)

    def delete(self, storage_reference: str, options: MediaDeleteOptions) -> None:
        self._object_path(storage_reference).unlink(missing_ok=True)

    def _ensure_dirs(self) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise MediaStorageConfigurationError("media.storage_root_symlink", "Media storage root is unsafe.")
        for directory in [self.objects_dir, self.materialized_dir, self.quarantine_dir, self.metadata_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def _safe_root(self, root: Path) -> Path:
        resolved = root.expanduser().resolve()
        if resolved.exists() and not resolved.is_dir():
            raise MediaStorageConfigurationError("media.storage_root_invalid", "Media storage root is invalid.")
        return resolved

    def _object_path(self, storage_reference: str) -> Path:
        if not storage_reference.startswith("local-object:"):
            raise MediaUnsafePathError("media.storage_reference_invalid", "Media storage reference is invalid.")
        object_id = storage_reference.split(":", maxsplit=1)[1]
        if not object_id.isalnum():
            raise MediaUnsafePathError("media.storage_reference_invalid", "Media storage reference is invalid.")
        path = (self.objects_dir / object_id[:2] / object_id[2:4] / object_id).resolve()
        if self.objects_dir.resolve() not in path.parents:
            raise MediaUnsafePathError("media.path_escape", "Media storage reference escapes the storage root.")
        return path
