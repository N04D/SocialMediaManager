"""Website analytics data quality summaries."""

from __future__ import annotations

from .models import ProviderMetricObservation, WebsiteAnalyticsDataQualityReport


class WebsiteAnalyticsQualityService:
    def build_report(
        self,
        account_id: str,
        site_identifier: str,
        observations: list[ProviderMetricObservation],
        *,
        partial_queries: int = 0,
        provider_warnings: tuple[str, ...] = (),
    ) -> WebsiteAnalyticsDataQualityReport:
        total = max(len(observations), 1)
        exact = len([item for item in observations if item.attribution_quality == "complete"])
        conflicting = len([item for item in observations if item.attribution_quality == "conflicting"])
        unattributed = len([item for item in observations if item.attribution_quality == "unattributed"])
        status = "complete"
        if partial_queries:
            status = "partial"
        elif conflicting:
            status = "conflicting"
        elif unattributed == len(observations) and observations:
            status = "unattributed"
        elif not observations:
            status = "delayed"
        return WebsiteAnalyticsDataQualityReport(
            account_id=account_id,
            site_identifier=site_identifier,
            period="latest_sync",
            freshness="fresh" if observations else "delayed",
            completeness="partial" if partial_queries else "complete",
            attribution_coverage=(total - unattributed) / total,
            exact_attribution_rate=exact / total,
            conflicting_attribution_rate=conflicting / total,
            unattributed_rate=unattributed / total,
            missing_metrics=(),
            partial_queries=partial_queries,
            provider_warnings=provider_warnings,
            stale_readmodels=0,
            status=status,
        )


__all__ = ["WebsiteAnalyticsQualityService"]
