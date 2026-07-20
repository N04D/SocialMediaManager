from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .contracts import MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION, media_contract_payload
from .errors import MediaNotFoundError, MediaStorageUnavailableError
from .models import (
    MediaDeleteOptions,
    MediaInput,
    MediaMaterialization,
    MediaMaterializeOptions,
    MediaObjectMetadata,
    MediaStoreOptions,
    StoredMedia,
)
from .utils import guess_mime_type, read_media_input, safe_extension_for_mime, sha256_bytes, validate_mime


class InMemoryMediaStorageProvider:
    provider_id = "provider.media.storage.memory"

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.actions: list[tuple[str, dict]] = []
        self.fail_actions: set[str] = set()
        self._tmp = TemporaryDirectory()

    def close(self) -> None:
        self._tmp.cleanup()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def simulate_failure(self, action: str) -> None:
        self.fail_actions.add(action)

    def _maybe_fail(self, action: str) -> None:
        if action in self.fail_actions:
            raise MediaStorageUnavailableError(
                "media.storage_unavailable", "Media storage is unavailable.", retryable=True
            )

    def health_check(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "status": "ready",
            "ok": True,
            "storage_type": "memory",
            "capabilities": [
                "media.storage",
                "media.storage.store",
                "media.storage.read",
                "media.storage.materialize",
                "media.storage.delete",
            ],
            **media_contract_payload(implemented_storage_version=MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION),
        }

    def store(self, source: MediaInput, options: MediaStoreOptions) -> StoredMedia:
        self._maybe_fail("store")
        mime_type, mime_status = guess_mime_type(source)
        validate_mime(mime_type, options.allowed_mime_types)
        data = read_media_input(source, maximum_size=options.maximum_size)
        checksum = sha256_bytes(data)
        reference = f"memory-object:{uuid4().hex}"
        self.objects[reference] = {
            "data": data,
            "mime_type": mime_type,
            "checksum": checksum,
            "mime_status": mime_status,
        }
        self.actions.append(("store", {"reference": reference, "checksum": checksum}))
        return StoredMedia(
            storage_reference=reference,
            provider_id=self.provider_id,
            file_size=len(data),
            mime_type=mime_type,
            checksum=checksum,
            stored_at="memory",
            provider_metadata={"mime_status": mime_status},
        )

    def exists(self, storage_reference: str) -> bool:
        return storage_reference in self.objects

    def stat(self, storage_reference: str) -> MediaObjectMetadata:
        item = self.objects.get(storage_reference)
        if item is None:
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        return MediaObjectMetadata(
            file_size=len(item["data"]),
            mime_type=item["mime_type"],
            checksum=item["checksum"],
            created_at="memory",
            updated_at="memory",
            exists=True,
            provider_metadata={"mime_status": item.get("mime_status", "")},
        )

    def open_stream(self, storage_reference: str):
        item = self.objects.get(storage_reference)
        if item is None:
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        yield item["data"]

    def materialize(self, storage_reference: str, options: MediaMaterializeOptions) -> MediaMaterialization:
        item = self.objects.get(storage_reference)
        if item is None:
            raise MediaNotFoundError("media.not_found", "Media object was not found.")
        path = Path(self._tmp.name) / f"{uuid4().hex}{safe_extension_for_mime(item['mime_type'])}"
        path.write_bytes(item["data"])
        self.actions.append(("materialize", {"reference": storage_reference, "path": str(path.name)}))
        return MediaMaterialization(
            id=f"mat_{uuid4().hex}",
            asset_id="",
            variant_id="",
            provider_id=self.provider_id,
            local_path=path,
            created_at="memory",
            expires_at="memory",
            cleanup_required=True,
            checksum=item["checksum"],
            purpose=options.purpose,
        )

    def cleanup_materialization(self, materialization: MediaMaterialization) -> None:
        materialization.local_path.unlink(missing_ok=True)

    def delete(self, storage_reference: str, options: MediaDeleteOptions) -> None:
        self._maybe_fail("delete")
        self.objects.pop(storage_reference, None)
        self.actions.append(("delete", {"reference": storage_reference}))
