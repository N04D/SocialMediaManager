"""Deterministic Markdown and frontmatter rendering."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC
from urllib.parse import quote, urlparse

from .errors import MarkdownWebsiteRenderError
from .models import RenderedMarkdown, WebsitePublicationSnapshot
from .paths import render_template
from .profiles import FrontmatterProfile, get_profile, safe_yaml_scalar
from .slug import slugify, validate_slug


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MarkdownSafetyValidator:
    def validate(self, body: str, profile: FrontmatterProfile) -> tuple[str, ...]:
        warnings: list[str] = []
        checks = {
            "script": re.search(r"<\s*script\b", body, re.IGNORECASE),
            "javascript_url": re.search(r"javascript\s*:", body, re.IGNORECASE),
            "event_handler": re.search(r"\son[a-z]+\s*=", body, re.IGNORECASE),
            "raw_html": re.search(r"<[a-zA-Z][^>]*>", body),
            "mdx_import": re.search(r"^\s*(import|export)\s+", body, re.MULTILINE),
            "template_code": re.search(r"({%|{{|<%|%})", body),
        }
        for key, match in checks.items():
            if not match:
                continue
            action = profile.markdown_policy.get(key, "deny")
            if action == "deny":
                raise MarkdownWebsiteRenderError(
                    f"markdown_website.markdown.{key}", "Markdown contains blocked syntax."
                )
            if action == "warn":
                warnings.append(f"{key}_present")
        return tuple(warnings)


class MarkdownRenderer:
    def __init__(self, safety: MarkdownSafetyValidator | None = None) -> None:
        self.safety = safety or MarkdownSafetyValidator()

    def render(
        self, snapshot: WebsitePublicationSnapshot, profile: FrontmatterProfile | None = None
    ) -> RenderedMarkdown:
        profile = profile or get_profile(snapshot.website_profile_id)
        variant = snapshot.variant
        slug = validate_slug(variant.slug) if variant.slug else slugify(variant.title)
        published_at = variant.published_at or variant.updated_at
        updated_at = variant.updated_at or variant.published_at
        if published_at is None or updated_at is None:
            raise MarkdownWebsiteRenderError(
                "markdown_website.render.date_missing", "Publication dates must be snapshotted."
            )
        pub = published_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        upd = updated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        public_url = resolve_public_url(snapshot, slug)
        values = {
            "title": variant.title,
            "slug": slug,
            "date": pub,
            "lastmod": upd,
            "status": variant.status,
            "description": variant.description or variant.summary,
            "canonical_url": variant.canonical_url or public_url,
            "tags": list(variant.tags),
            "hero_image": "",
            "content_item_id": snapshot.content_item_id,
            "content_revision_id": snapshot.content_revision_id,
            "channel_variant_id": snapshot.channel_variant_id,
            "publication_plan_id": snapshot.publication_plan_id,
            "publication_target_id": snapshot.publication_target_id,
            "publication_attempt_id": snapshot.publication_attempt_id,
            "publication_snapshot_checksum": snapshot.publication_snapshot_checksum,
            "website_profile_id": profile.id,
            "website_profile_version": profile.version,
        }
        for key, value in sorted(variant.custom_frontmatter.items()):
            if not profile.custom_value_allowed(key):
                raise MarkdownWebsiteRenderError(
                    "markdown_website.frontmatter.custom_key", "Custom frontmatter key is not allowlisted."
                )
            values[key] = value
        warnings = self.safety.validate(variant.markdown_body, profile)
        frontmatter = render_frontmatter(values, profile)
        body = variant.markdown_body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        marker = f"<!-- smm-content-revision:{snapshot.content_revision_id} -->"
        markdown = f"{frontmatter}\n{marker}\n\n{body}\n"
        relpath = render_markdown_path(snapshot, slug, profile)
        checksum = sha256_text(markdown)
        return RenderedMarkdown(relpath, public_url, markdown, markdown.encode("utf-8"), checksum, warnings)


def render_frontmatter(values: dict[str, object], profile: FrontmatterProfile) -> str:
    lines = ["---"]
    keys = list(profile.frontmatter_keys) + sorted(key for key in values if key not in profile.frontmatter_keys)
    for key in keys:
        value = values.get(key)
        if isinstance(value, list | tuple):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {safe_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {safe_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def render_markdown_path(snapshot: WebsitePublicationSnapshot, slug: str, profile: FrontmatterProfile) -> str:
    date = snapshot.variant.published_at or snapshot.variant.updated_at
    if date is None:
        raise MarkdownWebsiteRenderError(
            "markdown_website.render.date_missing", "Publication dates must be snapshotted."
        )
    return render_template(
        profile.file_template,
        {
            "content_root": snapshot.account_config.content_root,
            "slug": slug,
            "year": f"{date.year:04d}",
            "month": f"{date.month:02d}",
            "day": f"{date.day:02d}",
            "language": snapshot.variant.language or snapshot.account_config.default_language,
        },
    )


def resolve_public_url(snapshot: WebsitePublicationSnapshot, slug: str) -> str:
    date = snapshot.variant.published_at or snapshot.variant.updated_at
    if date is None:
        raise MarkdownWebsiteRenderError(
            "markdown_website.render.date_missing", "Publication dates must be snapshotted."
        )
    template = snapshot.account_config.public_url_template
    values = {
        "slug": quote(slug),
        "year": f"{date.year:04d}",
        "month": f"{date.month:02d}",
        "day": f"{date.day:02d}",
        "language": quote(snapshot.variant.language or snapshot.account_config.default_language),
    }
    url = template.format(**values)
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise MarkdownWebsiteRenderError("markdown_website.url.scheme", "Public URL must use https outside fixtures.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise MarkdownWebsiteRenderError("markdown_website.url.invalid", "Public URL is invalid.")
    base_host = urlparse(snapshot.account_config.public_base_url).hostname
    if base_host and parsed.hostname != base_host:
        raise MarkdownWebsiteRenderError("markdown_website.url.host", "Public URL must stay on the configured host.")
    return url
