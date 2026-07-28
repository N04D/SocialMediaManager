"""Plausible response parsing into provider-neutral observations."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlparse

from src.core.website_analytics.errors import WebsiteAnalyticsProviderError
from src.core.website_analytics.models import (
    ProviderMetricObservation,
    WebsiteAnalyticsAccount,
    WebsiteAnalyticsQuery,
    sanitize_dimensions,
    stable_checksum,
    utc_now_iso,
)
from src.core.website_analytics.sync import GENERIC_METRIC_MAP


def parse_plausible_response(
    account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery, payload: dict[str, Any]
) -> tuple[list[ProviderMetricObservation], dict[str, Any]]:
    if not isinstance(payload.get("results"), list) or not isinstance(payload.get("meta", {}), dict):
        raise WebsiteAnalyticsProviderError("schema_mismatch", "Plausible response schema was not recognized.")
    warnings: list[str] = []
    meta = payload.get("meta", {})
    if meta.get("imports_warning"):
        warnings.append("imports_warning")
    if meta.get("metric_warnings"):
        warnings.append("metric_warnings")
    observations: list[ProviderMetricObservation] = []
    query_fingerprint = query.fingerprint()
    for row_index, row in enumerate(payload["results"]):
        dimensions = row.get("dimensions", [])
        metrics = row.get("metrics", [])
        if not isinstance(dimensions, list) or not isinstance(metrics, list):
            raise WebsiteAnalyticsProviderError("schema_mismatch", "Plausible result row was malformed.")
        dim_map = sanitize_dimensions(
            {
                _dimension_name(name): dimensions[index]
                for index, name in enumerate(query.dimensions)
                if index < len(dimensions)
            }
        )
        if dim_map.get("landing_url"):
            for key, value in parse_qsl(urlparse(dim_map["landing_url"]).query, keep_blank_values=False):
                if key in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "smm_attribution_id"}:
                    dim_map.setdefault(key, value)
        for metric_index, metric in enumerate(query.metric_keys):
            if metric_index >= len(metrics):
                continue
            generic_key, aggregation = GENERIC_METRIC_MAP.get(
                metric, (f"provider.plausible.{metric}", "provider-defined")
            )
            value = metrics[metric_index]
            if value is None:
                continue
            source_fingerprint = stable_checksum(
                {
                    "provider": account.provider_id,
                    "account": account.id,
                    "site": account.site_identifier,
                    "metric": generic_key,
                    "period": [query.start_at, query.end_at],
                    "dimensions": dim_map,
                    "row": row_index,
                }
            )
            observations.append(
                ProviderMetricObservation(
                    provider_id=account.provider_id,
                    provider_account_id=account.id,
                    site_identifier=account.site_identifier,
                    metric_key=generic_key,
                    value=float(value),
                    unit=_unit_for_metric(metric),
                    period_start=query.start_at,
                    period_end=query.end_at,
                    dimensions=dim_map,
                    source_fingerprint=source_fingerprint,
                    provider_query_fingerprint=query_fingerprint,
                    collected_at=utc_now_iso(),
                    aggregation=aggregation,
                    content_item_id=query.publication_bindings.get("content_item_id", ""),
                    content_revision_id=query.publication_bindings.get("content_revision_id", ""),
                    website_target_id=query.publication_bindings.get("website_target_id", ""),
                    website_attempt_id=query.publication_bindings.get("website_attempt_id", ""),
                    campaign_id=query.publication_bindings.get("campaign_id", ""),
                )
            )
    return observations, {
        "warnings": tuple(warnings),
        "total_rows": int(meta.get("total_rows", len(observations)) or 0),
    }


def _dimension_name(name: str) -> str:
    return {
        "event:page": "landing_url",
        "visit:source": "source",
        "visit:utm_source": "utm_source",
        "visit:utm_medium": "utm_medium",
        "visit:utm_campaign": "utm_campaign",
        "visit:utm_content": "utm_content",
        "event:name": "event_name",
        "event:props:cta_id": "cta_id",
        "event:props:smm_attribution_id": "smm_attribution_id",
    }.get(name, name)


def _unit_for_metric(metric: str) -> str:
    if metric in {"bounce_rate", "conversion_rate", "scroll_depth"}:
        return "percent"
    if metric in {"visit_duration", "time_on_page"}:
        return "seconds"
    return "count"


__all__ = ["parse_plausible_response"]
