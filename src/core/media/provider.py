from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from .models import (
    MediaDeleteOptions,
    MediaInput,
    MediaMaterialization,
    MediaMaterializeOptions,
    MediaObjectMetadata,
    MediaStoreOptions,
    StoredMedia,
)


class MediaStorageProvider(Protocol):
    provider_id: str

    def health_check(self) -> dict: ...

    def store(self, source: MediaInput, options: MediaStoreOptions) -> StoredMedia: ...

    def exists(self, storage_reference: str) -> bool: ...

    def stat(self, storage_reference: str) -> MediaObjectMetadata: ...

    def open_stream(self, storage_reference: str) -> Iterator[bytes]: ...

    def materialize(self, storage_reference: str, options: MediaMaterializeOptions) -> MediaMaterialization: ...

    def cleanup_materialization(self, materialization: MediaMaterialization) -> None: ...

    def delete(self, storage_reference: str, options: MediaDeleteOptions) -> None: ...
