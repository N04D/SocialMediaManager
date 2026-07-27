"""Deterministic slug handling."""

from __future__ import annotations

import re
import unicodedata

from .errors import MarkdownWebsitePathError

RESERVED_SLUGS = {"admin", "api", "assets", "static", "media", "index", "404", "feed", "rss", "sitemap"}


def slugify(title: str, *, separator: str = "-", max_length: int = 80, reserved: set[str] | None = None) -> str:
    if separator not in {"-", "_"}:
        raise MarkdownWebsitePathError("markdown_website.slug.invalid_separator", "Invalid slug separator.")
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    slug = re.sub(r"[^a-z0-9]+", separator, lowered).strip(separator)
    slug = re.sub(f"{re.escape(separator)}+", separator, slug)[:max_length].strip(separator)
    validate_slug(slug, reserved=reserved)
    return slug


def validate_slug(slug: str, *, reserved: set[str] | None = None) -> str:
    blocked = RESERVED_SLUGS | (reserved or set())
    if not slug or slug in {".", ".."}:
        raise MarkdownWebsitePathError("markdown_website.slug.empty", "Slug must not be empty.")
    if any(item in slug for item in ("/", "\\", "?", "#")):
        raise MarkdownWebsitePathError("markdown_website.slug.path_separator", "Slug must not contain path syntax.")
    if any(ord(char) < 32 for char in slug):
        raise MarkdownWebsitePathError("markdown_website.slug.control", "Slug must not contain control characters.")
    if slug.lower() in blocked:
        raise MarkdownWebsitePathError("markdown_website.slug.reserved", "Slug is reserved.")
    return slug
