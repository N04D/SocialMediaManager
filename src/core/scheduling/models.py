from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PublicationScheduleStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RecurrenceFrequency(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduleOccurrenceStatus(StrEnum):
    PROJECTED = "projected"
    DUE = "due"
    MATERIALIZING = "materializing"
    MATERIALIZED = "materialized"
    READY = "ready"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    ATTENTION_REQUIRED = "attention_required"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


@dataclass
class PublicationSchedule:
    id: str
    workspace_id: str
    name: str
    description: str = ""
    status: str = PublicationScheduleStatus.DRAFT.value
    timezone: str = "UTC"
    starts_at_local: str = ""
    starts_at_utc: str = ""
    recurrence_rule_id: str = ""
    schedule_policy_id: str = ""
    template_snapshot_id: str = ""
    authorization_id: str = ""
    campaign_id: str = ""
    next_occurrence_at: str = ""
    last_occurrence_at: str = ""
    materialized_until: str = ""
    generation_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    paused_at: str = ""
    paused_by: str = ""
    pause_reason: str = ""
    cancelled_at: str = ""
    cancelled_by: str = ""
    cancellation_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecurrenceRule:
    id: str
    frequency: str
    interval: int = 1
    by_weekday: list[int] = field(default_factory=list)
    by_month_day: list[int] = field(default_factory=list)
    count: int = 0
    until_local: str = ""
    until_utc: str = ""
    week_start: int = 0
    contract_version: str = "1.0"
    normalized_rule: dict[str, Any] = field(default_factory=dict)
    checksum: str = ""


@dataclass
class SchedulePolicy:
    id: str
    workspace_id: str
    missed_occurrence_policy: str = "require_review"
    overlap_policy: str = "block_new"
    failure_policy: str = "require_review"
    uncertain_policy: str = "pause_schedule"
    authorization_policy: str = "per_occurrence_confirmation"
    dst_ambiguous_policy: str = "require_review"
    dst_nonexistent_policy: str = "require_review"
    monthly_invalid_date_policy: str = "skip_invalid_date"
    materialization_horizon_days: int = 30
    maximum_materialized_occurrences: int = 100
    maximum_pending_occurrences: int = 100
    minimum_spacing_seconds: int = 0
    catch_up_maximum: int = 3
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ScheduleTargetTemplate:
    channel_plugin_id: str
    channel_account_id: str
    capability: str
    channel_variant_id: str = ""
    media_relation_ids: list[str] = field(default_factory=list)
    position: int = 0
    offset_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleTemplateSnapshot:
    id: str
    workspace_id: str
    source_publication_plan_id: str
    source_plan_checksum: str
    content_item_id: str
    source_revision_id: str
    revision_checksum: str
    target_templates: list[dict[str, Any]] = field(default_factory=list)
    media_relation_ids: list[str] = field(default_factory=list)
    content_requirement_versions: dict[str, str] = field(default_factory=dict)
    media_requirement_versions: dict[str, str] = field(default_factory=dict)
    timezone: str = "UTC"
    created_at: str = ""
    created_by: str = ""
    checksum: str = ""
    contract_version: str = "1.0"


@dataclass
class ScheduleOccurrence:
    id: str
    workspace_id: str
    schedule_id: str
    campaign_id: str
    occurrence_key: str
    generation_version: int
    sequence_number: int
    scheduled_at_local: str
    timezone: str
    scheduled_at_utc: str
    status: str = ScheduleOccurrenceStatus.PROJECTED.value
    source_template_snapshot_id: str = ""
    template_snapshot_checksum: str = ""
    publication_plan_id: str = ""
    publication_target_ids: list[str] = field(default_factory=list)
    authorization_id: str = ""
    materialized_at: str = ""
    dispatched_at: str = ""
    completed_at: str = ""
    skipped_at: str = ""
    skip_reason: str = ""
    blocked_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleExclusion:
    id: str
    schedule_id: str
    exclusion_type: str
    starts_at_local: str
    ends_at_local: str = ""
    timezone: str = "UTC"
    reason: str = ""
    created_at: str = ""
    created_by: str = ""


@dataclass
class ScheduleAuthorization:
    id: str
    workspace_id: str
    schedule_id: str
    template_snapshot_checksum: str
    authorized_by: str
    authorized_at: str
    valid_from: str
    valid_until: str
    maximum_occurrences: int
    consumed_occurrences: int = 0
    allowed_channel_account_ids: list[str] = field(default_factory=list)
    allowed_capabilities: list[str] = field(default_factory=list)
    status: str = "draft"
    revoked_at: str = ""
    revoked_by: str = ""
    revoke_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalendarEntry:
    id: str
    workspace_id: str
    entry_type: str
    starts_at: str
    ends_at: str
    timezone: str
    title: str
    status: str
    channel_plugin_id: str = ""
    channel_account_id: str = ""
    campaign_id: str = ""
    schedule_id: str = ""
    occurrence_id: str = ""
    plan_id: str = ""
    target_id: str = ""
    attempt_id: str = ""
    attention_required: bool = False
    blockers: list[str] = field(default_factory=list)
    safe_summary: str = ""


@dataclass
class Campaign:
    id: str
    workspace_id: str
    name: str
    description: str = ""
    status: str = CampaignStatus.DRAFT.value
    starts_at: str = ""
    ends_at: str = ""
    timezone: str = "UTC"
    coordination_policy_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    paused_at: str = ""
    pause_reason: str = ""
    cancelled_at: str = ""
    cancellation_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CampaignMember:
    id: str
    campaign_id: str
    member_type: str
    member_id: str
    position: int = 0
    required: bool = True
    active: bool = True
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CampaignCoordinationPolicy:
    id: str
    workspace_id: str
    failure_policy: str = "require_review"
    uncertain_policy: str = "pause_campaign"
    pause_propagation: str = "stop_future_only"
    cancellation_propagation: str = "cancel_pending"
    maximum_active_occurrences: int = 50
    maximum_active_targets: int = 100
    enabled: bool = True
