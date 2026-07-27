"""Media helpers for website publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .errors import MarkdownWebsitePathError
from .models import WebsiteMediaReference
from .paths import ensure_under

MIME_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


@dataclass(frozen=True)
class MaterializedMedia:
    reference: WebsiteMediaReference
    source_path: Path
    checksum: str
    mime_type: str


def website_media_filename(reference: WebsiteMediaReference) -> str:
    ext = MIME_EXTENSIONS.get(reference.mime_type)
    if not ext:
        raise MarkdownWebsitePathError("markdown_website.media.mime", "Unsupported media MIME type.")
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in reference.safe_name).strip(
        "-_"
    )
    if not safe_name:
        safe_name = "media"
    return f"{reference.asset_id}-{reference.variant_id}-{safe_name}.{ext}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_materialized_media(repo_root: Path, media_root: str, item: MaterializedMedia) -> tuple[str, str]:
    if item.mime_type != item.reference.mime_type or item.checksum != item.reference.checksum:
        raise MarkdownWebsitePathError(
            "markdown_website.media.integrity", "Materialized media failed integrity checks."
        )
    filename = website_media_filename(item.reference)
    relative = str(Path(media_root) / filename)
    destination = ensure_under(repo_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = item.source_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != item.checksum:
        raise MarkdownWebsitePathError("markdown_website.media.checksum", "Media checksum mismatch.")
    destination.write_bytes(data)
    return relative, item.checksum
