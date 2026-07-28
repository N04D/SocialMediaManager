"""Plausible Stats API v2 query translation."""

from __future__ import annotations

from src.core.website_analytics.models import WebsiteAnalyticsQuery

PLAUSIBLE_ENDPOINT = "/api/v2/query"
PLAUSIBLE_ALLOWED_METRICS = {
    "visitors",
    "pageviews",
    "visits",
    "bounce_rate",
    "visit_duration",
    "time_on_page",
    "scroll_depth",
    "events",
    "conversion_rate",
}
PLAUSIBLE_ALLOWED_DIMENSIONS = {
    "event:page",
    "visit:source",
    "visit:utm_source",
    "visit:utm_medium",
    "visit:utm_campaign",
    "visit:utm_content",
    "event:name",
    "event:props:cta_id",
    "event:props:smm_attribution_id",
    "time",
}


def plausible_query_body(query: WebsiteAnalyticsQuery, *, offset: int = 0) -> dict:
    return {
        "site_id": query.site_identifier,
        "metrics": list(query.metric_keys),
        "date_range": [query.start_at, query.end_at],
        "dimensions": list(query.dimensions),
        "filters": [[operator, dimension, list(values)] for operator, dimension, values in query.filters],
        "include": {"total_rows": True},
        "pagination": {"limit": query.page_size, "offset": offset},
    }


__all__ = ["PLAUSIBLE_ALLOWED_DIMENSIONS", "PLAUSIBLE_ALLOWED_METRICS", "PLAUSIBLE_ENDPOINT", "plausible_query_body"]
