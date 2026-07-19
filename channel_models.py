from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelConnection:
    id: str
    channel_id: str
    mode: str
    status: str
    connected_at: str = ""
    last_checked_at: str = ""
    last_error: str = ""
    local_profile_path: str = ""
    capabilities_snapshot_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    archived_profile_path: str = ""
    active_job_id: str = ""
    active_job_type: str = ""
    active_worker_id: str = ""
    active_claimed_at: str = ""
    last_connect_diagnostics_json: dict[str, Any] = field(default_factory=dict)
    browser_provider_id: str = ""


@dataclass
class ContentDerivative:
    id: str
    source_document_id: str
    channel_id: str
    output_type: str
    title: str
    body: str
    status: str
    generation_metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    last_error: str = ""


@dataclass
class ApprovalRecord:
    id: str
    derivative_id: str
    approved_by: str
    approved_at: str
    status: str
    revoked_at: str = ""
    created_at: str = ""


@dataclass
class PublishJob:
    id: str
    derivative_id: str
    channel_id: str
    status: str
    requested_at: str
    started_at: str = ""
    finished_at: str = ""
    attempt_count: int = 0
    max_attempts: int = 2
    last_step: str = ""
    error_code: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    result_url: str = ""
    result_external_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    run_mode: str = "dry_run"
    unknown_result: bool = False
    claimed_by: str = ""
    claimed_at: str = ""
    lease_expires_at: str = ""
    heartbeat_at: str = ""
    submitted_at: str = ""
    manual_verification_required: bool = False
    result_details_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishedPost:
    id: str
    derivative_id: str
    source_document_id: str
    channel_id: str
    external_id: str
    external_url: str
    published_at: str
    publish_job_id: str
    status: str
    raw_result_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MetricJob:
    id: str
    published_post_id: str
    channel_id: str
    status: str
    scheduled_for: str
    requested_at: str
    started_at: str = ""
    finished_at: str = ""
    attempt_count: int = 0
    max_attempts: int = 2
    error_code: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    claimed_by: str = ""
    claimed_at: str = ""
    lease_expires_at: str = ""
    heartbeat_at: str = ""


@dataclass
class PostMetricSnapshot:
    id: str
    published_post_id: str
    channel_id: str
    captured_at: str
    impressions: int | None = None
    views: int | None = None
    reactions: int | None = None
    comments: int | None = None
    reposts: int | None = None
    shares: int | None = None
    clicks: int | None = None
    raw_metrics_json: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str = ""
    created_at: str = ""
    delta_views: int | None = None
    delta_impressions: int | None = None
    delta_reactions: int | None = None
    delta_comments: int | None = None
    delta_reposts: int | None = None
    seconds_since_previous_snapshot: int | None = None


@dataclass
class WorkerHeartbeat:
    worker_id: str
    worker_type: str
    channel_id: str
    status: str
    last_seen_at: str
    current_job_id: str = ""
    last_error: str = ""
    started_at: str = ""
    current_job_type: str = ""
    process_id: int = 0


@dataclass
class ChannelJobLog:
    id: str
    channel_id: str
    job_type: str
    job_id: str
    status: str
    last_step: str
    started_at: str = ""
    finished_at: str = ""
    error_code: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    result_url: str = ""
    created_at: str = ""
    worker_id: str = ""
