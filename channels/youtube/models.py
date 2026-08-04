from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class YouTubePublishPlan:
    execution_id: str
    asset_id: str
    asset_path: str
    asset_checksum: str
    title: str
    description: str
    privacy: str = "private"
    notify_subscribers: bool = False
    channel_account_id: str = ""
    channel_id: str = ""
    variant_id: str = ""
    revision_id: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    mime_type: str = "video/mp4"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class YouTubePublicationEvidence:
    execution_id: str
    asset_id: str
    asset_checksum: str
    channel_account_id: str
    remote_video_id: str = ""
    remote_url: str = ""
    requested_privacy: str = "private"
    observed_privacy: str = ""
    processing_status: str = "pending"
    status: str = "queued"
    session_created: bool = False
    confirmed_plan_checksum: str = ""
    bytes_confirmed: int = 0
    variant_id: str = ""
    revision_id: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
