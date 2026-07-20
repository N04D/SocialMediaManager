from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from .errors import MediaChecksumMismatchError, MediaFileTooLargeError, MediaMimeTypeError
from .models import MediaInput, MediaType

DEFAULT_CHUNK_SIZE = 1024 * 1024
IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}


def media_type_for_mime(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return MediaType.IMAGE.value
    if mime_type.startswith("video/"):
        return MediaType.VIDEO.value
    if mime_type.startswith("audio/"):
        return MediaType.AUDIO.value
    if mime_type:
        return MediaType.DOCUMENT.value
    return MediaType.UNKNOWN.value


def guess_mime_type(source: MediaInput) -> tuple[str, str]:
    declared = source.declared_mime_type.strip().lower()
    if declared:
        return declared, "declared_only"
    filename = source.original_filename or (source.local_path.name if source.local_path else "")
    guessed = mimetypes.guess_type(filename)[0] or ""
    return (guessed.lower(), "extension_only") if guessed else ("application/octet-stream", "unknown")


def validate_mime(mime_type: str, allowed: tuple[str, ...]) -> None:
    if allowed and mime_type not in allowed:
        raise MediaMimeTypeError(
            "media.mime_type_not_allowed",
            "Media type is not allowed for this operation.",
            {"mime_type": mime_type},
        )


def read_media_input(source: MediaInput, *, maximum_size: int) -> bytes:
    if source.data is not None:
        data = source.data
    elif source.local_path is not None:
        data = source.local_path.read_bytes()
    elif source.stream is not None:
        data = source.stream.read()
    else:
        data = b""
    if len(data) > maximum_size:
        raise MediaFileTooLargeError("media.file_too_large", "Media file is too large.")
    if source.expected_size and len(data) != source.expected_size:
        raise MediaFileTooLargeError("media.size_mismatch", "Media file size did not match the expected size.")
    if source.expected_checksum:
        checksum = sha256_bytes(data)
        if checksum != source.expected_checksum:
            raise MediaChecksumMismatchError("media.checksum_mismatch", "Media checksum did not match.")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_extension_for_mime(mime_type: str) -> str:
    return {k: v for k, v in {"image/jpeg": ".jpg", "image/png": ".png"}.items()}.get(mime_type, ".bin")


def safe_display_name(filename: str) -> str:
    return Path(filename).name[:160] or "media"
