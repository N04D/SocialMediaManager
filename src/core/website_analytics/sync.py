"""Bounded website analytics query planning and sync orchestration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .errors import WebsiteAnalyticsError
from .models import WebsiteAnalyticsAccount, WebsiteAnalyticsQuery, chunk_period, stable_checksum

GENERIC_METRIC_MAP = {
    "visitors": ("website.unique_visitors", "unique_estimate"),
    "pageviews": ("website.page_views", "sum"),
    "visits": ("website.visits", "sum"),
    "bounce_rate": ("provider.plausible.bounce_rate", "provider-defined"),
    "visit_duration": ("website.average_visit_duration_seconds", "average"),
    "time_on_page": ("provider.plausible.time_on_page", "provider-defined"),
    "scroll_depth": ("website.scroll_depth_average", "average"),
    "events": ("website.conversions", "sum"),
    "conversion_rate": ("website.conversion_rate", "ratio"),
}
ALLOWED_METRICS = frozenset(GENERIC_METRIC_MAP)
ALLOWED_DIMENSIONS = frozenset(
    {
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
)


class WebsiteAnalyticsQueryPlanner:
    def __init__(self, *, max_days_per_query: int = 31, max_page_size: int = 1000) -> None:
        self.max_days_per_query = max(1, max_days_per_query)
        self.max_page_size = max(100, max_page_size)

    def validate_query(self, query: WebsiteAnalyticsQuery) -> None:
        if not query.metric_keys or any(metric not in ALLOWED_METRICS for metric in query.metric_keys):
            raise WebsiteAnalyticsError("website_analytics.invalid_metric", "Analytics metric is not allowlisted.")
        if any(dimension not in ALLOWED_DIMENSIONS for dimension in query.dimensions):
            raise WebsiteAnalyticsError(
                "website_analytics.invalid_dimension", "Analytics dimension is not allowlisted."
            )
        if query.page_size > self.max_page_size:
            raise WebsiteAnalyticsError("website_analytics.page_size_too_large", "Analytics page size exceeds limit.")
        for operator, dimension, _values in query.filters:
            if operator not in {"is", "is_not", "contains"} or dimension not in ALLOWED_DIMENSIONS:
                raise WebsiteAnalyticsError("website_analytics.invalid_filter", "Analytics filter is not allowlisted.")

    def plan(
        self,
        account: WebsiteAnalyticsAccount,
        *,
        sync_type: str = "incremental",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[WebsiteAnalyticsQuery]:
        now = datetime.now(UTC)
        period_end = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=UTC)
        end = end_at or period_end
        if sync_type == "initial":
            start = start_at or (end - timedelta(days=89))
        elif sync_type == "correction":
            start = start_at or (end - timedelta(days=7))
        else:
            start = start_at or (end - timedelta(days=2))
        if end - start > timedelta(days=370):
            raise WebsiteAnalyticsError("website_analytics.period_too_large", "Analytics sync period is too large.")
        queries: list[WebsiteAnalyticsQuery] = []
        for chunk_start, chunk_end in chunk_period(start, end, days=self.max_days_per_query):
            queries.extend(
                [
                    WebsiteAnalyticsQuery(
                        account_id=account.id,
                        site_identifier=account.site_identifier,
                        metric_keys=("visitors", "pageviews", "visits", "visit_duration"),
                        dimensions=("event:page",),
                        filters=(),
                        start_at=chunk_start.isoformat().replace("+00:00", "Z"),
                        end_at=chunk_end.isoformat().replace("+00:00", "Z"),
                        granularity=account.default_date_granularity,
                        page_size=self.max_page_size,
                    ),
                    WebsiteAnalyticsQuery(
                        account_id=account.id,
                        site_identifier=account.site_identifier,
                        metric_keys=("visitors", "visits"),
                        dimensions=("visit:utm_source", "visit:utm_campaign", "visit:utm_content"),
                        filters=(),
                        start_at=chunk_start.isoformat().replace("+00:00", "Z"),
                        end_at=chunk_end.isoformat().replace("+00:00", "Z"),
                        granularity=account.default_date_granularity,
                        page_size=self.max_page_size,
                    ),
                    WebsiteAnalyticsQuery(
                        account_id=account.id,
                        site_identifier=account.site_identifier,
                        metric_keys=("events",),
                        dimensions=("event:name", "event:props:cta_id", "event:props:smm_attribution_id"),
                        filters=(),
                        start_at=chunk_start.isoformat().replace("+00:00", "Z"),
                        end_at=chunk_end.isoformat().replace("+00:00", "Z"),
                        granularity=account.default_date_granularity,
                        page_size=self.max_page_size,
                    ),
                ]
            )
        for query in queries:
            self.validate_query(query)
        return queries


def cursor_payload(account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery, *, offset: int) -> dict[str, Any]:
    payload = {
        "provider": account.provider_id,
        "account_id": account.id,
        "site_identifier": account.site_identifier,
        "query": asdict(query),
        "offset": offset,
    }
    payload["checksum"] = stable_checksum(payload)
    return payload


__all__ = [
    "ALLOWED_DIMENSIONS",
    "ALLOWED_METRICS",
    "GENERIC_METRIC_MAP",
    "WebsiteAnalyticsQueryPlanner",
    "cursor_payload",
]
