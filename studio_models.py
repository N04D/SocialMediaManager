from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentItem:
    id: str
    title: str
    subtitle: str
    slug: str
    status: str
    channels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    editor_json: dict[str, Any] = field(default_factory=dict)
    markdown_body: str = ""
    html_body: str = ""
    cover_image_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    published_at: str = ""
    linkedin_post_urn: str = ""
    instagram_media_id: str = ""
    substack_post_id: str = ""
    x_post_id: str = ""


@dataclass
class Publication:
    id: str
    content_item_id: str
    platform: str
    external_id: str
    external_url: str
    status: str
    published_at: str = ""
    last_stats_sync_at: str = ""


@dataclass
class PostStatsSnapshot:
    id: str
    publication_id: str
    platform: str
    snapshot_at: str
    impressions: int | None = None
    reach: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    followers_gained: int | None = None
    profile_views: int | None = None
    raw_payload_json: dict[str, Any] | list[Any] | str | None = None
