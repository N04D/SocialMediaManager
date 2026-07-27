"""Public models used by the Markdown Website channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MarkdownWebsiteAccountConfig:
    id: str
    workspace_id: str
    account_id: str
    display_name: str
    repository_reference_id: str
    branch: str
    content_root: str
    media_root: str
    public_base_url: str
    public_url_template: str
    frontmatter_profile_id: str
    default_author: str = ""
    default_language: str = "en"
    default_status: str = "published"
    default_tags: tuple[str, ...] = ()
    git_identity_reference: str = ""
    push_policy: str = "commit_only"
    verification_policy: str = "commit_only"
    analytics_profile_id: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class WebsiteRepositoryReference:
    id: str
    workspace_id: str
    display_name: str
    managed_checkout_root: Path
    allowed_remote_names: tuple[str, ...] = ("origin",)
    allowed_remote_hosts: tuple[str, ...] = ()
    allowed_branches: tuple[str, ...] = ("main",)
    allowed_content_roots: tuple[str, ...] = ("content", "articles")
    allowed_media_roots: tuple[str, ...] = ("static/media", "public/media")
    git_auth_secret_reference: str = ""
    read_only_metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class WebsiteCallToAction:
    label: str
    destination: str
    type: str = "external"
    tracking_id: str = ""


@dataclass(frozen=True)
class WebsiteSeoMetadata:
    title: str = ""
    description: str = ""
    canonical_url: str = ""
    noindex: bool = False
    nofollow: bool = False
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    twitter_card: str = "summary_large_image"


@dataclass(frozen=True)
class WebsiteMediaReference:
    asset_id: str
    variant_id: str
    safe_name: str
    mime_type: str
    checksum: str
    role: str = "inline"
    alt_text: str = ""
    caption: str = ""
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class WebsiteVariant:
    title: str
    markdown_body: str
    slug: str = ""
    summary: str = ""
    language: str = "en"
    author: str = ""
    published_at: datetime | None = None
    updated_at: datetime | None = None
    status: str = "published"
    description: str = ""
    tags: tuple[str, ...] = ()
    hero_media_asset_id: str = ""
    canonical_url: str = ""
    cta: WebsiteCallToAction | None = None
    seo: WebsiteSeoMetadata = field(default_factory=WebsiteSeoMetadata)
    custom_frontmatter: dict[str, Any] = field(default_factory=dict)
    inline_media: tuple[WebsiteMediaReference, ...] = ()


@dataclass(frozen=True)
class WebsitePublicationSnapshot:
    content_item_id: str
    content_revision_id: str
    channel_variant_id: str
    publication_plan_id: str
    publication_target_id: str
    publication_attempt_id: str
    publication_snapshot_checksum: str
    website_profile_id: str
    website_profile_version: str
    account_config: MarkdownWebsiteAccountConfig
    variant: WebsiteVariant


@dataclass(frozen=True)
class RenderedMarkdown:
    relative_path: str
    public_url: str
    markdown: str
    markdown_bytes: bytes
    checksum: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebsiteMutationManifest:
    created_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    original_checksums: dict[str, str]
    resulting_checksums: dict[str, str]
    media_bindings: dict[str, str]
    rendered_markdown_checksum: str
    snapshot_checksum: str


@dataclass(frozen=True)
class WebsitePublicationEvidence:
    repository_reference_id: str
    branch: str
    base_commit: str
    publication_commit: str
    remote_name: str
    remote_commit: str
    markdown_relative_path: str
    media_relative_paths: tuple[str, ...]
    rendered_markdown_checksum: str
    media_checksums: dict[str, str]
    public_url: str
    snapshot_checksum: str
    revision_binding: dict[str, str]
    verification_status: str
    verification_timestamp: str
    mutation_manifest: WebsiteMutationManifest


@dataclass(frozen=True)
class WebsiteMetricObservation:
    metric_name: str
    value: float
    content_item_id: str
    content_revision_id: str
    website_target_id: str
    publication_attempt_id: str = ""
    channel_variant_id: str = ""
    campaign: str = ""
    source_social_target_id: str = ""
    attribution_id: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentFunnelPerformance:
    content_item_id: str
    content_revision_id: str
    website_target_id: str
    social_target_ids: tuple[str, ...]
    impressions: float = 0
    social_engagement: float = 0
    link_clicks: float = 0
    website_visits: float = 0
    engaged_visits: float = 0
    cta_clicks: float = 0
    conversions: float = 0
    conversion_value: float = 0
    conversion_rate: float = 0
    source_breakdown: dict[str, float] = field(default_factory=dict)
    campaign_breakdown: dict[str, float] = field(default_factory=dict)
    time_window: str = ""
