"""Provider-neutral website analytics models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


ProviderCapabilityStatus = Literal["supported", "unsupported", "conditionally_supported"]


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    status: ProviderCapabilityStatus
    notes: str = ""


@dataclass(frozen=True)
class AnalyticsProviderOriginReference:
    id: str
    provider_id: str
    display_name: str
    scheme: str
    host: str
    optional_base_path: str = ""
    allowed_redirect_origins: tuple[str, ...] = field(default_factory=tuple)
    hosted_or_self_hosted: str = "hosted"
    enabled: bool = True

    def base_url(self) -> str:
        path = "/" + self.optional_base_path.strip("/") if self.optional_base_path else ""
        return urlunparse((self.scheme, self.host, path, "", "", ""))


@dataclass(frozen=True)
class WebsiteAnalyticsAccount:
    id: str
    workspace_id: str
    provider_id: str
    display_name: str
    origin_reference_id: str
    site_identifier: str
    secret_reference_id: str
    timezone: str
    default_date_granularity: str
    enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class WebsiteAnalyticsEventMapping:
    id: str
    workspace_id: str
    account_id: str
    provider_event_name: str
    provider_property_filters: dict[str, str]
    internal_event_type: str
    cta_id: str = ""
    conversion_type: str = ""
    conversion_value_policy: str = "none"
    enabled: bool = True
    version: int = 1


@dataclass(frozen=True)
class WebsiteAnalyticsQuery:
    account_id: str
    site_identifier: str
    metric_keys: tuple[str, ...]
    dimensions: tuple[str, ...]
    filters: tuple[tuple[str, str, tuple[str, ...]], ...]
    start_at: str
    end_at: str
    granularity: str = "day"
    page_size: int = 1000
    cursor: str = ""
    publication_bindings: dict[str, str] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return stable_checksum(asdict(self))


@dataclass(frozen=True)
class ProviderMetricObservation:
    provider_id: str
    provider_account_id: str
    site_identifier: str
    metric_key: str
    value: float
    unit: str
    period_start: str
    period_end: str
    dimensions: dict[str, str]
    source_fingerprint: str
    provider_query_fingerprint: str
    collected_at: str
    aggregation: str
    content_item_id: str = ""
    content_revision_id: str = ""
    website_target_id: str = ""
    website_attempt_id: str = ""
    campaign_id: str = ""
    attribution_quality: str = "unattributed"
    correction_of_observation_id: str = ""


@dataclass(frozen=True)
class WebsiteAnalyticsAttribution:
    observation_id: str
    website_target_id: str
    website_attempt_id: str
    content_item_id: str
    content_revision_id: str
    campaign_id: str
    source_social_target_id: str
    source_social_attempt_id: str
    attribution_id: str
    attribution_method: str
    confidence: float
    quality_status: str


@dataclass(frozen=True)
class WebsiteAnalyticsSyncState:
    id: str
    workspace_id: str
    account_id: str
    site_identifier: str
    sync_type: str
    status: str
    cursor: str
    high_watermark: str
    correction_window_start: str
    last_started_at: str
    last_completed_at: str
    last_successful_at: str
    next_run_at: str
    attempt_count: int
    last_error_code: str
    lease_owner: str
    lease_expires_at: str
    version: int = 1


@dataclass(frozen=True)
class ProviderRateLimitState:
    account_id: str
    limit: int
    remaining: int
    reset_at: str
    retry_after: int
    source: str
    observed_at: str


@dataclass(frozen=True)
class WebsiteAnalyticsDataQualityReport:
    account_id: str
    site_identifier: str
    period: str
    freshness: str
    completeness: str
    attribution_coverage: float
    exact_attribution_rate: float
    conflicting_attribution_rate: float
    unattributed_rate: float
    missing_metrics: tuple[str, ...]
    partial_queries: int
    provider_warnings: tuple[str, ...]
    stale_readmodels: int
    status: str


def sanitize_dimensions(raw: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "smm_attribution_id",
        "landing_url",
        "source",
        "referrer_source",
        "event_name",
        "cta_id",
        "conversion_type",
        "path",
    }
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        lowered = str(key).lower()
        if lowered in {"ip", "ip_address", "user-agent", "user_agent", "cookie", "email", "name"}:
            continue
        if key in allowed:
            cleaned[key] = str(value)[:512]
    return cleaned


def normalize_landing_url(url: str, *, allowed_host: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or parsed.hostname != allowed_host:
        return ""
    safe_params = {
        key: value
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "smm_attribution_id"}
    }
    path = quote(parsed.path or "/", safe="/%")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(safe_params), ""))


def chunk_period(start: datetime, end: datetime, *, days: int) -> list[tuple[datetime, datetime]]:
    if end < start:
        return []
    chunks: list[tuple[datetime, datetime]] = []
    current = start
    step = timedelta(days=max(1, days))
    while current <= end:
        chunk_end = min(end, current + step - timedelta(seconds=1))
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(seconds=1)
    return chunks


__all__ = [
    "AnalyticsProviderOriginReference",
    "ProviderCapability",
    "ProviderMetricObservation",
    "ProviderRateLimitState",
    "WebsiteAnalyticsAccount",
    "WebsiteAnalyticsAttribution",
    "WebsiteAnalyticsDataQualityReport",
    "WebsiteAnalyticsEventMapping",
    "WebsiteAnalyticsQuery",
    "WebsiteAnalyticsSyncState",
    "chunk_period",
    "normalize_landing_url",
    "sanitize_dimensions",
    "stable_checksum",
    "utc_now_iso",
]
