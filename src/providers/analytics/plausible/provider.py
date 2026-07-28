"""Plausible Stats API v2 read-only provider adapter."""

from __future__ import annotations

from src.core.website_analytics.contracts import PLAUSIBLE_ANALYTICS_ADAPTER_VERSION
from src.core.website_analytics.errors import WebsiteAnalyticsProviderError
from src.core.website_analytics.models import (
    AnalyticsProviderOriginReference,
    ProviderCapability,
    ProviderMetricObservation,
    ProviderRateLimitState,
    WebsiteAnalyticsAccount,
    WebsiteAnalyticsQuery,
    utc_now_iso,
)
from src.core.website_analytics.provider import InMemorySafeHttpFacade, SafeHttpFacade, SafeHttpRequest
from src.core.website_analytics.sync import WebsiteAnalyticsQueryPlanner

from .parser import parse_plausible_response
from .queries import PLAUSIBLE_ENDPOINT, plausible_query_body


def plausible_origin_reference() -> AnalyticsProviderOriginReference:
    return AnalyticsProviderOriginReference(
        id="plausible-cloud",
        provider_id="analytics.plausible",
        display_name="Plausible Cloud",
        scheme="https",
        host="plausible.io",
        allowed_redirect_origins=("https://plausible.io",),
        hosted_or_self_hosted="hosted",
        enabled=True,
    )


class PlausibleWebsiteAnalyticsProvider:
    provider_id = "analytics.plausible"
    provider_version = PLAUSIBLE_ANALYTICS_ADAPTER_VERSION
    provider_family = "website_analytics"
    execution_mode = "built_in_in_process"
    data_access = "read_only"

    def __init__(
        self, http_facade: SafeHttpFacade | None = None, planner: WebsiteAnalyticsQueryPlanner | None = None
    ) -> None:
        self.http = http_facade or InMemorySafeHttpFacade()
        self.planner = planner or WebsiteAnalyticsQueryPlanner()

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        supported = {
            "page_metrics",
            "visitor_metrics",
            "session_metrics",
            "traffic_sources",
            "campaign_dimensions",
            "page_dimensions",
            "custom_events",
            "custom_properties",
            "goal_metrics",
            "conversion_metrics",
            "scroll_metrics",
            "duration_metrics",
            "time_series",
            "pagination",
            "historical_sync",
            "incremental_sync",
        }
        return tuple(
            ProviderCapability(name, "supported" if name in supported else "unsupported")
            for name in (
                "page_metrics",
                "visitor_metrics",
                "session_metrics",
                "traffic_sources",
                "campaign_dimensions",
                "page_dimensions",
                "custom_events",
                "custom_properties",
                "goal_metrics",
                "conversion_metrics",
                "scroll_metrics",
                "duration_metrics",
                "time_series",
                "pagination",
                "historical_sync",
                "incremental_sync",
            )
        )

    def validate_account(self, account: WebsiteAnalyticsAccount) -> dict:
        query = self.planner.plan(account, sync_type="incremental")[0]
        response = self._query(query, account)
        if response.status_code == 401:
            raise WebsiteAnalyticsProviderError(
                "authentication_failed", "Plausible credential was rejected.", needs_configuration=True
            )
        if response.status_code == 403:
            raise WebsiteAnalyticsProviderError(
                "authorization_failed", "Plausible site is not authorized.", needs_configuration=True
            )
        if response.status_code == 404:
            raise WebsiteAnalyticsProviderError(
                "site_not_found", "Plausible site was not found.", needs_configuration=True
            )
        if response.status_code == 429:
            raise WebsiteAnalyticsProviderError("rate_limited", "Plausible rate limit is active.", retryable=True)
        if response.status_code >= 500:
            raise WebsiteAnalyticsProviderError("provider_unavailable", "Plausible is unavailable.", retryable=True)
        if "application/json" not in response.headers.get("content-type", "application/json"):
            raise WebsiteAnalyticsProviderError("malformed_response", "Plausible response content type was invalid.")
        if response.json_body is None:
            raise WebsiteAnalyticsProviderError("malformed_response", "Plausible response did not contain JSON.")
        self.normalize(account, query, response.json_body)
        return {
            "valid": True,
            "provider_id": self.provider_id,
            "site_access": True,
            "schema": "valid",
            "read_only": True,
            "checked_at": utc_now_iso(),
        }

    def get_health(self, account: WebsiteAnalyticsAccount) -> dict:
        try:
            validation = self.validate_account(account)
        except WebsiteAnalyticsProviderError as exc:
            return {"status": "failed", "safe_error_code": exc.code, "retryable": exc.retryable}
        return {"status": "healthy", **validation}

    def plan_sync(self, account: WebsiteAnalyticsAccount, sync_type: str) -> list[WebsiteAnalyticsQuery]:
        return self.planner.plan(account, sync_type=sync_type)

    def collect(
        self, account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery
    ) -> tuple[list[ProviderMetricObservation], dict]:
        self.planner.validate_query(query)
        response = self._query(query, account)
        if response.status_code == 429:
            return [], {
                "rate_limit": ProviderRateLimitState(account.id, 0, 0, "", 60, "response", utc_now_iso()),
                "warnings": ("rate_limited",),
            }
        if response.status_code >= 400 or response.json_body is None:
            raise WebsiteAnalyticsProviderError(
                "provider_unavailable", "Plausible query failed safely.", retryable=response.status_code >= 500
            )
        return self.normalize(account, query, response.json_body)

    def normalize(
        self, account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery, payload: dict
    ) -> tuple[list[ProviderMetricObservation], dict]:
        return parse_plausible_response(account, query, payload)

    def reconcile_cursor(self, cursor: str) -> dict:
        return {
            "status": "valid" if cursor in {"", "completed"} else "cursor_incompatible",
            "provider_id": self.provider_id,
        }

    def _query(self, query: WebsiteAnalyticsQuery, account: WebsiteAnalyticsAccount):
        return self.http.send(
            SafeHttpRequest(
                method="POST",
                origin_reference_id=account.origin_reference_id,
                url_path=PLAUSIBLE_ENDPOINT,
                json_body=plausible_query_body(query),
                auth_secret_reference_id=account.secret_reference_id,
                headers={
                    "Content-Type": "application/json",
                },
            )
        )


__all__ = ["PlausibleWebsiteAnalyticsProvider", "plausible_origin_reference"]
