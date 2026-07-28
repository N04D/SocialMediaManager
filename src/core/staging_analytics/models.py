"""Provider-neutral staging analytics certification models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def opaque_run_id(workspace_id: str, profile_id: str, seed: str) -> str:
    digest = stable_checksum({"workspace_id": workspace_id, "profile_id": profile_id, "seed": seed})[:24]
    return f"smm_synthetic_run_{digest}"


@dataclass(frozen=True)
class StagingSiteOriginReference:
    id: str
    workspace_id: str
    display_name: str
    scheme: str
    host: str
    optional_base_path: str
    environment: str
    synthetic_only: bool
    allowed_page_paths: tuple[str, ...]
    allowed_redirect_origins: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def base_url(self) -> str:
        base_path = "/" + self.optional_base_path.strip("/") if self.optional_base_path else ""
        return urlunparse((self.scheme, self.host, base_path, "", "", ""))

    def page_url(self, page_path: str) -> str:
        safe_path = page_path if page_path.startswith("/") else f"/{page_path}"
        if self.optional_base_path:
            prefix = "/" + self.optional_base_path.strip("/")
            safe_path = prefix + safe_path
        return urlunparse((self.scheme, self.host, safe_path, "", "", ""))


@dataclass(frozen=True)
class SyntheticAnalyticsPageProfile:
    id: str
    version: str
    display_name: str
    page_path: str
    instrumentation_profile_id: str
    expected_page_context: dict[str, str]
    expected_cta: dict[str, str]
    expected_conversion: dict[str, str]
    consent_mode: str
    noindex_required: bool
    synthetic_marker: str
    checksum: str = ""

    def with_checksum(self) -> SyntheticAnalyticsPageProfile:
        payload = asdict(self)
        payload["checksum"] = ""
        return self.__class__(**{**payload, "checksum": stable_checksum(payload)})


@dataclass(frozen=True)
class StagingAnalyticsCertificationProfile:
    id: str
    workspace_id: str
    staging_origin_reference_id: str
    analytics_account_id: str
    synthetic_page_profile_id: str
    expected_event_mapping_ids: tuple[str, ...]
    browser_name: str
    browser_mode: str
    maximum_wait_seconds: int
    initial_poll_delay_seconds: int
    maximum_poll_delay_seconds: int
    polling_multiplier: float
    maximum_poll_attempts: int
    correction_window: str
    enabled: bool
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StagingAnalyticsCertificationRun:
    id: str
    workspace_id: str
    profile_id: str
    run_id: str
    status: str
    page_url_reference: str
    analytics_account_id: str
    instrumentation_manifest_id: str
    expected_event_bindings: tuple[dict[str, Any], ...]
    expected_attribution_id: str
    browser_evidence_ids: tuple[str, ...]
    provider_observation_ids: tuple[str, ...]
    reconciliation_status: str
    started_at: str
    browser_completed_at: str
    provider_observed_at: str
    completed_at: str
    safe_error_code: str
    checksum: str


@dataclass(frozen=True)
class StagingBrowserRequestEvidence:
    id: str
    run_id: str
    event_type: str
    event_name: str
    destination_origin_reference: str
    method: str
    safe_property_names: tuple[str, ...]
    safe_property_fingerprint: str
    instrumentation_version: str
    occurred_at: str
    accepted_by_browser_runtime: bool
    checksum: str


@dataclass(frozen=True)
class SyntheticProviderObservationQuery:
    account_id: str
    run_id: str
    expected_event_names: tuple[str, ...]
    expected_property_filters: dict[str, str]
    period_start: str
    period_end: str
    page_path: str
    attribution_id: str


@dataclass(frozen=True)
class ProviderObservedReconciliationResult:
    run_id: str
    expected_events: tuple[str, ...]
    observed_events: tuple[str, ...]
    missing_events: tuple[str, ...]
    conflicting_events: tuple[str, ...]
    duplicate_events: tuple[str, ...]
    delayed_events: tuple[str, ...]
    mapping_mismatches: tuple[str, ...]
    observation_ids: tuple[str, ...]
    attribution_status: str
    quality_status: str
    reconciled_at: str


@dataclass(frozen=True)
class StagingAnalyticsCertificationReport:
    framework_version: str
    profile_id: str
    run_id: str
    commit_sha: str
    staging_origin_reference_id: str
    analytics_provider_id: str
    analytics_account_id: str
    browser_name: str
    browser_version: str
    browser_mode: str
    instrumentation_version: str
    synthetic_marker_verified: bool
    noindex_verified: bool
    consent_verified: bool
    browser_events_verified: bool
    provider_observed_status: str
    observed_event_count: int
    expected_event_count: int
    mapping_status: str
    attribution_status: str
    data_quality: str
    required_secrets_present: bool
    live_staging_executed: bool
    deterministic_only: bool
    started_at: str
    completed_at: str
    safe_warnings: tuple[str, ...]
    certification_passed: bool
    checksum: str


def report_with_checksum(report: StagingAnalyticsCertificationReport) -> StagingAnalyticsCertificationReport:
    payload = asdict(report)
    payload["checksum"] = ""
    return report.__class__(**{**payload, "checksum": stable_checksum(payload)})


def bounded_poll_schedule(initial: int, maximum: int, multiplier: float, attempts: int) -> tuple[int, ...]:
    delays: list[int] = []
    current = max(0, initial)
    for _ in range(max(0, attempts)):
        delays.append(min(maximum, current))
        current = max(current + 1, int(current * multiplier))
    return tuple(delays)


def window_end(start_iso: str, seconds: int) -> str:
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    return (
        (start + timedelta(seconds=seconds)).astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def safe_url_reference(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


__all__ = [
    "ProviderObservedReconciliationResult",
    "StagingAnalyticsCertificationProfile",
    "StagingAnalyticsCertificationReport",
    "StagingAnalyticsCertificationRun",
    "StagingBrowserRequestEvidence",
    "StagingSiteOriginReference",
    "SyntheticAnalyticsPageProfile",
    "SyntheticProviderObservationQuery",
    "bounded_poll_schedule",
    "opaque_run_id",
    "report_with_checksum",
    "safe_url_reference",
    "stable_checksum",
    "utc_now_iso",
    "window_end",
]
