"""Provider-neutral website instrumentation models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


OPAQUE_RE = re.compile(r"^smm_[a-z0-9_]+_[a-f0-9]{24}$")


@dataclass(frozen=True)
class WebsiteInstrumentationProfile:
    id: str
    version: str
    display_name: str
    website_framework: str
    analytics_provider_id: str
    event_schema_version: str
    page_context_strategy: str
    cta_strategy: str
    outbound_click_strategy: str
    conversion_strategy: str
    consent_mode: str
    script_delivery_mode: str
    public_marker_strategy: str
    supported_features: tuple[str, ...]
    checksum: str = ""

    def with_checksum(self) -> WebsiteInstrumentationProfile:
        payload = asdict(self)
        payload["checksum"] = ""
        return self.__class__(**{**payload, "checksum": stable_checksum(payload)})


@dataclass(frozen=True)
class WebsitePageContext:
    schema_version: str
    page_id: str
    canonical_url: str
    page_path: str
    content_id: str
    revision_id: str
    publication_id: str
    campaign_id: str
    language: str
    content_type: str
    published_at: str
    instrumentation_manifest_checksum: str


@dataclass(frozen=True)
class WebsiteCtaEventContext:
    cta_id: str
    cta_type: str
    placement: str
    destination_kind: str
    destination_origin_class: str


@dataclass(frozen=True)
class WebsiteOutboundClickContext:
    link_id: str
    destination_origin_class: str
    destination_host_reference: str
    placement: str


@dataclass(frozen=True)
class WebsiteConversionEventContext:
    conversion_id: str
    conversion_type: str
    cta_id: str
    value: float | None = None
    currency: str = ""
    outcome: str = ""


@dataclass(frozen=True)
class WebsiteInstrumentationEvent:
    schema_version: str
    event_type: str
    event_name: str
    page_context: WebsitePageContext
    event_context: dict[str, str | float]
    attribution_context: dict[str, str]
    consent_context: dict[str, str]


@dataclass(frozen=True)
class WebsiteInstrumentationConfig:
    id: str
    workspace_id: str
    website_account_id: str
    analytics_account_id: str
    profile_id: str
    consent_mode: str
    enabled: bool
    cta_event_name: str
    outbound_event_name: str
    conversion_event_name: str
    attribution_policy: str
    script_delivery_mode: str
    expected_script_origin_reference: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WebsiteInstrumentationManifest:
    id: str
    workspace_id: str
    website_account_id: str
    analytics_account_id: str
    content_item_id: str
    content_revision_id: str
    publication_plan_id: str
    publication_target_id: str
    publication_attempt_id: str
    campaign_id: str
    public_url: str
    page_path: str
    page_context: WebsitePageContext
    cta_bindings: tuple[dict[str, str], ...]
    conversion_bindings: tuple[dict[str, str], ...]
    expected_events: tuple[dict[str, Any], ...]
    attribution_policy: str
    consent_mode: str
    profile_id: str
    profile_version: str
    script_version: str
    created_at: str
    checksum: str


@dataclass(frozen=True)
class InstrumentationMappingDriftReport:
    config_id: str
    status: str
    missing_mappings: tuple[str, ...]
    obsolete_mappings: tuple[str, ...]
    property_mismatches: tuple[str, ...]
    profile_mismatch: bool
    generated_at: str


@dataclass(frozen=True)
class WebsiteInstrumentationQualityReport:
    website_account_id: str
    analytics_account_id: str
    publication_target_id: str
    manifest_status: str
    static_page_status: str
    browser_runtime_status: str
    provider_observed_status: str
    mapping_drift_status: str
    consent_mode: str
    page_context_status: str
    cta_coverage: dict[str, int]
    conversion_coverage: dict[str, int]
    attribution_parameter_status: str
    duplicate_runtime_status: str
    pii_risk_status: str
    last_verified_at: str
    safe_warnings: tuple[str, ...]
    overall_status: str


ALLOWED_ATTRIBUTION_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "smm_attribution_id"}


def normalize_attribution_from_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    values: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key in ALLOWED_ATTRIBUTION_PARAMS and len(value) <= 160 and re.match(r"^[A-Za-z0-9_.:-]+$", value):
            values[key] = value
    return values


def canonical_without_tracking(url: str) -> str:
    parsed = urlparse(url)
    safe_query = [(k, v) for k, v in parse_qsl(parsed.query) if k not in ALLOWED_ATTRIBUTION_PARAMS]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", urlencode(safe_query), ""))


__all__ = [
    "ALLOWED_ATTRIBUTION_PARAMS",
    "InstrumentationMappingDriftReport",
    "OPAQUE_RE",
    "WebsiteConversionEventContext",
    "WebsiteCtaEventContext",
    "WebsiteInstrumentationConfig",
    "WebsiteInstrumentationEvent",
    "WebsiteInstrumentationManifest",
    "WebsiteInstrumentationProfile",
    "WebsiteInstrumentationQualityReport",
    "WebsiteOutboundClickContext",
    "WebsitePageContext",
    "canonical_without_tracking",
    "normalize_attribution_from_url",
    "stable_checksum",
    "utc_now_iso",
]
