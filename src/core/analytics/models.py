from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MetricValueType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENTAGE = "percentage"
    DURATION_MS = "duration_ms"
    BOOLEAN = "boolean"


class MetricUnit(StrEnum):
    COUNT = "count"
    RATIO = "ratio"
    PERCENT = "percent"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"


class MetricSemanticType(StrEnum):
    EXPOSURE = "exposure"
    REACH = "reach"
    IMPRESSION = "impression"
    ENGAGEMENT = "engagement"
    REACTION = "reaction"
    COMMENT = "comment"
    SHARE = "share"
    CLICK = "click"
    FOLLOWER_CHANGE = "follower_change"
    VIEW_DURATION = "view_duration"
    COMPLETION = "completion"
    UNKNOWN = "unknown"


class MetricAggregationType(StrEnum):
    LATEST = "latest"
    SUM = "sum"
    MAXIMUM = "maximum"
    MINIMUM = "minimum"
    AVERAGE = "average"
    WEIGHTED_AVERAGE = "weighted_average"
    NON_AGGREGATABLE = "non_aggregatable"


class MetricObservationStatus(StrEnum):
    VALID = "valid"
    PROVISIONAL = "provisional"
    CORRECTED = "corrected"
    SUPERSEDED = "superseded"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"
    DUPLICATE = "duplicate"


class AttributionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"
    HISTORICAL = "historical"


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    channel_plugin_id: str
    metric_key: str
    display_name: str
    description: str
    version: str
    value_type: str
    unit: str
    semantic_type: str
    aggregation_type: str
    direction: str = "higher_is_better"
    denominator_metric_key: str = ""
    comparable_group: str = ""
    cumulative: bool = True
    monotonic_expected: bool = False
    nullable: bool = True
    source_scope: str = "publication"
    created_at: str = ""
    deprecated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedMetricDefinition:
    id: str
    metric_key: str
    display_name: str
    version: str
    formula_type: str
    numerator_keys: tuple[str, ...] = field(default_factory=tuple)
    denominator_keys: tuple[str, ...] = field(default_factory=tuple)
    multiplier: float = 1.0
    minimum_denominator: float = 1.0
    comparable_group: str = ""
    aggregation_type: str = MetricAggregationType.NON_AGGREGATABLE.value
    null_policy: str = "null_when_missing"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelMetricObservationInput:
    remote_publication_id: str
    publication_id: str
    metric_key: str
    value: int | float | bool | None
    observed_at: str
    window_start: str = ""
    window_end: str = ""
    source_version: str = ""
    source_evidence_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricObservation:
    id: str
    workspace_id: str
    channel_plugin_id: str
    channel_account_id: str
    publication_id: str
    remote_publication_id: str
    metric_definition_id: str
    metric_key: str
    metric_definition_version: str
    observed_value: int | float | bool | None
    observed_at: str
    measurement_window_start: str = ""
    measurement_window_end: str = ""
    captured_at: str = ""
    source_type: str = ""
    source_version: str = ""
    source_run_id: str = ""
    source_evidence_reference: str = ""
    observation_key: str = ""
    status: str = MetricObservationStatus.VALID.value
    correction_of_observation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricObservationCorrection:
    id: str
    observation_id: str
    corrected_observation_id: str
    reason_code: str
    reason: str
    corrected_by: str
    corrected_at: str


@dataclass
class PublicationAttribution:
    id: str
    workspace_id: str
    publication_id: str
    remote_publication_id: str
    channel_plugin_id: str
    channel_account_id: str
    content_item_id: str = ""
    content_revision_id: str = ""
    content_revision_checksum: str = ""
    channel_variant_id: str = ""
    channel_variant_checksum: str = ""
    publication_plan_id: str = ""
    publication_target_id: str = ""
    schedule_id: str = ""
    schedule_occurrence_id: str = ""
    campaign_id: str = ""
    execution_attempt_id: str = ""
    execution_snapshot_checksum: str = ""
    media_relation_ids: list[str] = field(default_factory=list)
    media_asset_ids: list[str] = field(default_factory=list)
    media_variant_ids: list[str] = field(default_factory=list)
    content_requirement_version: str = ""
    media_requirement_version: str = ""
    published_at: str = ""
    remote_verified_at: str = ""
    created_at: str = ""
    attribution_checksum: str = ""
    status: str = AttributionStatus.UNRESOLVED.value
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyticsCollectionPolicy:
    workspace_id: str
    channel_plugin_id: str
    recent_publication_days: int = 30
    refresh_interval_hours: int = 24
    maximum_publications_per_run: int = 25
    stop_after_days: int = 90
    enabled: bool = True


@dataclass
class AnalyticsCollectionRun:
    id: str
    workspace_id: str
    channel_plugin_id: str
    channel_account_id: str
    started_at: str
    completed_at: str = ""
    status: str = "running"
    publication_count: int = 0
    observation_count: int = 0
    duplicate_count: int = 0
    failure_count: int = 0
    source_version: str = ""
    watermark: str = ""
    safe_error_codes: list[str] = field(default_factory=list)


@dataclass
class AnalyticsReadSnapshot:
    id: str
    workspace_id: str
    read_model_type: str
    subject_id: str
    filter_checksum: str
    generated_at: str
    source_observation_watermark: str
    attribution_watermark: str
    definition_versions: dict[str, str]
    payload: dict[str, Any]
    freshness: str = "unknown"
