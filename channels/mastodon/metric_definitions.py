from __future__ import annotations

from typing import Any

from src.core.analytics import MetricAggregationType, MetricDefinition, MetricSemanticType, MetricUnit, MetricValueType

MASTODON_METRIC_DEFINITION_VERSION = "1.0"
MASTODON_METRICS_SOURCE_VERSION = "mastodon.status.v1"


def _definition(metric_key: str, display_name: str, semantic_type: str, comparable_group: str) -> MetricDefinition:
    return MetricDefinition(
        id=f"channel.mastodon.{metric_key}.v1",
        channel_plugin_id="channel.mastodon",
        metric_key=metric_key,
        display_name=display_name,
        description=f"Mastodon {display_name.lower()} from the official Status resource.",
        version=MASTODON_METRIC_DEFINITION_VERSION,
        value_type=MetricValueType.INTEGER.value,
        unit=MetricUnit.COUNT.value,
        semantic_type=semantic_type,
        aggregation_type=MetricAggregationType.LATEST.value,
        comparable_group=comparable_group,
        cumulative=True,
        monotonic_expected=True,
        nullable=True,
        source_scope="publication",
        metadata={
            "measurement_window": "lifetime_to_date",
            "unavailable_metrics": ["impressions", "reach", "views", "clicks"],
        },
    )


def register_mastodon_metric_definitions(registry: Any, *, include_quotes: bool = False) -> None:
    registry.register(_definition("favourites", "Favourites", MetricSemanticType.REACTION.value, "reaction_count"))
    registry.register(_definition("replies", "Replies", MetricSemanticType.COMMENT.value, "comment_count"))
    registry.register(_definition("reblogs", "Reblogs", MetricSemanticType.SHARE.value, "share_count"))
    if include_quotes:
        registry.register(_definition("quotes", "Quotes", MetricSemanticType.SHARE.value, "share_count"))
