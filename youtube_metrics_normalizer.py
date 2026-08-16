from __future__ import annotations

from typing import Any

from src.core.content.publications import normalized_metric

YOUTUBE_METRICS_NORMALIZER_ID = "youtube.metrics.normalizer"
YOUTUBE_METRICS_NORMALIZER_VERSION = "0.1.0"
YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION = "youtube-data-api-video-statistics-local-v1"


def normalize_youtube_video_statistics(raw_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    statistics = raw_payload.get("statistics")
    if not isinstance(statistics, dict):
        statistics = raw_payload
    mapping = {
        "viewCount": "views",
        "likeCount": "likes",
        "commentCount": "comments",
        "shareCount": "shares",
    }
    normalized: dict[str, dict[str, Any]] = {}
    for provider_field, metric_key in mapping.items():
        if provider_field not in statistics:
            continue
        value = statistics[provider_field]
        if value is None:
            continue
        normalized[metric_key] = normalized_metric(
            metric_key,
            int(value),
            unit="count",
            value_type="integer",
            provider_source_field=f"statistics.{provider_field}",
        )
    return normalized
