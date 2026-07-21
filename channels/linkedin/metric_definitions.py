from __future__ import annotations

from typing import Any

from src.core.analytics import (
    MetricAggregationType,
    MetricDefinition,
    MetricSemanticType,
    MetricUnit,
    MetricValueType,
)

LINKEDIN_METRIC_DEFINITION_VERSION = "1.0"
LINKEDIN_METRICS_SOURCE_VERSION = "linkedin.metrics.v1"


def _definition(
    metric_key: str,
    display_name: str,
    semantic_type: str,
    comparable_group: str,
    *,
    monotonic_expected: bool = True,
) -> MetricDefinition:
    return MetricDefinition(
        id=f"channel.linkedin.{metric_key}.v1",
        channel_plugin_id="channel.linkedin",
        metric_key=metric_key,
        display_name=display_name,
        description=f"LinkedIn {display_name.lower()} captured by the existing metrics flow.",
        version=LINKEDIN_METRIC_DEFINITION_VERSION,
        value_type=MetricValueType.INTEGER.value,
        unit=MetricUnit.COUNT.value,
        semantic_type=semantic_type,
        aggregation_type=MetricAggregationType.LATEST.value,
        comparable_group=comparable_group,
        cumulative=True,
        monotonic_expected=monotonic_expected,
        nullable=True,
        source_scope="publication",
        metadata={"supported_application_limits": "Only fields parsed by the current LinkedIn metrics collector."},
    )


def register_linkedin_metric_definitions(registry: Any) -> None:
    registry.register(
        _definition(
            "impressions",
            "Impressions",
            MetricSemanticType.IMPRESSION.value,
            "exposure_count",
        )
    )
    registry.register(
        _definition(
            "views",
            "Views",
            MetricSemanticType.EXPOSURE.value,
            "exposure_count",
        )
    )
    registry.register(
        _definition(
            "reactions",
            "Reactions",
            MetricSemanticType.REACTION.value,
            "reaction_count",
        )
    )
    registry.register(
        _definition(
            "comments",
            "Comments",
            MetricSemanticType.COMMENT.value,
            "comment_count",
        )
    )
    registry.register(
        _definition(
            "reposts",
            "Reposts",
            MetricSemanticType.SHARE.value,
            "share_count",
        )
    )
    registry.register(
        _definition(
            "shares",
            "Shares",
            MetricSemanticType.SHARE.value,
            "share_count",
        )
    )
    registry.register(
        _definition(
            "clicks",
            "Clicks",
            MetricSemanticType.CLICK.value,
            "click_count",
        )
    )
