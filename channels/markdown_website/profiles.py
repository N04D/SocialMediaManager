"""Versioned frontmatter profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import MarkdownWebsiteConfigError


@dataclass(frozen=True)
class FrontmatterProfile:
    id: str
    version: str
    file_template: str
    frontmatter_keys: tuple[str, ...]
    custom_frontmatter_allowlist: tuple[str, ...] = ()
    markdown_policy: dict[str, str] = field(default_factory=dict)

    def custom_value_allowed(self, key: str) -> bool:
        return key in self.custom_frontmatter_allowlist


BASE_KEYS = (
    "title",
    "slug",
    "date",
    "lastmod",
    "status",
    "description",
    "canonical_url",
    "tags",
    "hero_image",
    "content_item_id",
    "content_revision_id",
    "channel_variant_id",
    "publication_plan_id",
    "publication_target_id",
    "publication_attempt_id",
    "publication_snapshot_checksum",
    "website_profile_id",
    "website_profile_version",
)

DEFAULT_POLICY = {
    "script": "deny",
    "javascript_url": "deny",
    "event_handler": "deny",
    "raw_html": "warn",
    "mdx_import": "deny",
    "template_code": "deny",
}

PROFILES: dict[str, FrontmatterProfile] = {
    "generic_yaml": FrontmatterProfile(
        "generic_yaml",
        "1.0",
        "{content_root}/{slug}.md",
        BASE_KEYS,
        ("layout", "category", "series"),
        DEFAULT_POLICY,
    ),
    "hugo": FrontmatterProfile(
        "hugo", "1.0", "{content_root}/{year}/{month}/{slug}.md", BASE_KEYS, ("draft",), DEFAULT_POLICY
    ),
    "jekyll": FrontmatterProfile("jekyll", "1.0", "{content_root}/{slug}.md", BASE_KEYS, ("layout",), DEFAULT_POLICY),
    "astro": FrontmatterProfile("astro", "1.0", "{content_root}/{slug}.md", BASE_KEYS, ("layout",), DEFAULT_POLICY),
    "eleventy": FrontmatterProfile(
        "eleventy", "1.0", "{content_root}/{slug}.md", BASE_KEYS, ("permalink",), DEFAULT_POLICY
    ),
    "next_mdx": FrontmatterProfile(
        "next_mdx",
        "1.0",
        "{content_root}/{slug}/index.mdx",
        BASE_KEYS,
        ("layout",),
        {**DEFAULT_POLICY, "mdx_import": "warn", "raw_html": "warn"},
    ),
}


def list_profiles() -> tuple[FrontmatterProfile, ...]:
    return tuple(PROFILES[key] for key in sorted(PROFILES))


def get_profile(profile_id: str) -> FrontmatterProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise MarkdownWebsiteConfigError("markdown_website.profile_unknown", "Unknown frontmatter profile.") from exc


def safe_yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
