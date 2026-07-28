from __future__ import annotations

import unittest

from src.core.website_analytics.attribution import WebsiteAnalyticsAttributionService
from src.core.website_analytics.models import ProviderMetricObservation, sanitize_dimensions


class WebsiteAnalyticsAttributionPhase25Tests(unittest.TestCase):
    def observation(self, dimensions: dict[str, str]) -> ProviderMetricObservation:
        return ProviderMetricObservation(
            provider_id="analytics.plausible",
            provider_account_id="analytics-account-plausible",
            site_identifier="example.com",
            metric_key="website.visits",
            value=1,
            unit="count",
            period_start="2026-07-28T00:00:00Z",
            period_end="2026-07-28T23:59:59Z",
            dimensions=dimensions,
            source_fingerprint="fp",
            provider_query_fingerprint="query",
            collected_at="2026-07-28T12:00:00Z",
            aggregation="sum",
        )

    def test_attribution_priority_and_conflicts(self) -> None:
        service = WebsiteAnalyticsAttributionService()
        known = {"attr-1": {"content_item_id": "content-1", "campaign_id": "campaign-1"}}
        exact = service.attribute("obs-1", self.observation({"smm_attribution_id": "attr-1"}), known)
        self.assertEqual(exact.attribution_method, "exact_attribution_id")
        conflict = service.attribute(
            "obs-2",
            self.observation({"smm_attribution_id": "attr-1", "utm_campaign": "campaign-2"}),
            known,
        )
        self.assertEqual(conflict.quality_status, "conflicting")
        campaign = service.attribute(
            "obs-3",
            self.observation({"utm_campaign": "campaign-1", "utm_content": "content-1"}),
            known,
        )
        self.assertEqual(campaign.attribution_method, "exact_campaign_and_content")
        source = service.attribute(
            "obs-4", self.observation({"utm_source": "linkedin", "utm_campaign": "campaign-1"}), known
        )
        self.assertEqual(source.attribution_method, "source_and_campaign")
        unattributed = service.attribute("obs-5", self.observation({"source": "direct"}), known)
        self.assertEqual(unattributed.attribution_method, "unattributed")

    def test_pii_dimensions_are_removed(self) -> None:
        cleaned = sanitize_dimensions(
            {
                "utm_source": "linkedin",
                "ip_address": "192.0.2.5",
                "user-agent": "browser",
                "cookie": "visitor",
                "email": "reader@example.invalid",
            }
        )
        self.assertEqual(cleaned, {"utm_source": "linkedin"})


if __name__ == "__main__":
    unittest.main()
