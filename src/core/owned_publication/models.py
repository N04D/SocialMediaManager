"""Models for the Owned Publication Workspace."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def stable_checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ContentDraft:
    id: str
    workspace_id: str
    title: str
    summary: str
    markdown_body: str
    tags: tuple[str, ...] = ()
    language: str = "en"
    author: str = ""
    status: str = "draft"
    version: int = 1
    updated_at: str = ""
    slug: str = ""

    @property
    def checksum(self) -> str:
        return stable_checksum(
            "\n".join([self.id, self.workspace_id, self.title, self.summary, self.markdown_body, ",".join(self.tags)])
        )


@dataclass(frozen=True)
class ContentRevision:
    id: str
    content_item_id: str
    workspace_id: str
    title: str
    summary: str
    markdown_body: str
    tags: tuple[str, ...]
    language: str
    author: str
    source_draft_version: int
    checksum: str
    created_at: str
    slug: str = ""


@dataclass(frozen=True)
class ChannelVariantDraft:
    id: str
    content_item_id: str
    content_revision_id: str
    channel: str
    text: str
    checksum: str
    accepted: bool = False
    generated: bool = False
    generation_binding: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceValidationResult:
    scope: str
    severity: str
    code: str
    message: str
    related_field: str = ""
    related_target: str = ""
    blocking: bool = False
    suggested_action: str = ""


@dataclass(frozen=True)
class ReadinessSummary:
    article: str
    website: str
    social_primary: str
    social_secondary: str
    dependencies: str
    schedule: str
    overall: str


@dataclass(frozen=True)
class PublicationTarget:
    id: str
    channel: str
    account_id: str
    variant_id: str
    schedule: str = "publish_now"
    status: str = "draft"
    verification_policy: str = ""
    snapshot_checksum: str = ""


@dataclass(frozen=True)
class PublicationPlan:
    id: str
    workspace_id: str
    content_item_id: str
    content_revision_id: str
    campaign: str
    targets: tuple[PublicationTarget, ...]
    dependencies: tuple[dict[str, str], ...]
    version: int = 1
    created_at: str = ""


@dataclass(frozen=True)
class ExecutionTimelineEvent:
    timestamp: str
    phase: str
    actor: str
    mutation_state: str
    status: str
    safe_evidence_summary: str = ""
    error_code: str = ""
    next_action: str = ""


@dataclass(frozen=True)
class PublicationEvidenceSummary:
    publication_id: str
    target_id: str
    channel: str
    content_revision_id: str
    snapshot_checksum: str
    public_url: str = ""
    relative_path: str = ""
    rendered_checksum: str = ""
    publication_commit: str = ""
    remote_commit: str = ""
    verification_status: str = "not_verified"
    verification_markers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationItem:
    id: str
    workspace_id: str
    publication_id: str
    target_id: str
    channel: str
    category: str
    mutation_state: str
    severity: str
    detected_at: str
    safe_evidence: dict[str, str]
    recommended_read_only_check: str
    allowed_repair: str = ""
    manual_action: str = ""


@dataclass(frozen=True)
class FunnelStep:
    name: str
    count: float
    rate_from_previous: float
    rate_from_first: float


@dataclass(frozen=True)
class ChannelComparison:
    channel: str
    impressions: float
    engagement: float
    clicks: float
    click_through_rate: float
    website_visits: float
    engaged_visits: float
    cta_clicks: float
    conversions: float
    conversion_rate: float
    attribution_quality: str


@dataclass(frozen=True)
class ArticlePerformanceInsight:
    conclusion: str
    supporting_metrics: dict[str, float]
    content_revision_id: str
    publication_target_ids: tuple[str, ...]
    period: str
    confidence: str
    evidence_links: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class RevisionComparison:
    content_item_id: str
    revisions: tuple[str, ...]
    title_changed: bool
    body_checksum_delta: tuple[str, ...]
    channel_variant_differences: dict[str, str]
    metric_summary: dict[str, float]
    time_period_warning: str


@dataclass(frozen=True)
class OwnedPublicationWorkspace:
    content_item_id: str
    workspace_id: str
    draft: ContentDraft
    active_revision: ContentRevision
    revision_history: tuple[ContentRevision, ...]
    variants: dict[str, ChannelVariantDraft]
    website_preview: dict[str, Any]
    frontmatter_preview: str
    markdown_preview_html: str
    validation: tuple[WorkspaceValidationResult, ...]
    readiness: ReadinessSummary
    publication_plan: PublicationPlan
    dependency_graph: dict[str, Any]
    schedule: dict[str, Any]
    timeline: tuple[ExecutionTimelineEvent, ...]
    evidence: tuple[PublicationEvidenceSummary, ...]
    reconciliation_queue: tuple[ReconciliationItem, ...]
    integrity: dict[str, Any]
    funnel: dict[str, Any]
    channel_comparison: tuple[ChannelComparison, ...]
    revision_comparison: RevisionComparison
    insights: tuple[ArticlePerformanceInsight, ...]
    data_quality: str
