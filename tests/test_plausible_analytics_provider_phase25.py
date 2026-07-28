from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.website_analytics.fake_provider import FakeWebsiteAnalyticsHttpFacade
from integrations.website_analytics.fixtures import plausible_invalid_token_response, plausible_schema_drift_response
from integrations.website_analytics.scenarios import plausible_account_payload
from src.core.website_analytics.errors import WebsiteAnalyticsProviderError
from src.core.website_analytics.provider import InMemorySafeHttpFacade
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.providers.analytics.plausible.queries import PLAUSIBLE_ENDPOINT


class PlausibleAnalyticsProviderPhase25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def service(self, facade=None) -> WebsiteAnalyticsService:
        return WebsiteAnalyticsService(database_path=Path(self.tmp.name) / "owned.sqlite3", http_facade=facade)

    def test_validate_collects_read_only_stats_api_v2(self) -> None:
        facade = FakeWebsiteAnalyticsHttpFacade()
        service = self.service(facade)
        service.create_account(plausible_account_payload())
        self.assertTrue(service.validate("analytics-account-plausible")["valid"])
        self.assertEqual(facade.requests[0].method, "POST")
        self.assertEqual(facade.requests[0].url_path, "/api/v2/query")
        self.assertEqual(facade.provider_writes, 0)

    def test_provider_errors_are_classified_safely(self) -> None:
        service = self.service(InMemorySafeHttpFacade({PLAUSIBLE_ENDPOINT: plausible_invalid_token_response()}))
        service.create_account(plausible_account_payload())
        with self.assertRaises(WebsiteAnalyticsProviderError) as ctx:
            service.validate("analytics-account-plausible")
        self.assertEqual(ctx.exception.code, "authentication_failed")
        service = self.service(InMemorySafeHttpFacade({PLAUSIBLE_ENDPOINT: plausible_schema_drift_response()}))
        service.create_account(plausible_account_payload() | {"id": "analytics-account-schema"})
        with self.assertRaises(WebsiteAnalyticsProviderError) as ctx:
            service.validate("analytics-account-schema")
        self.assertEqual(ctx.exception.code, "schema_mismatch")

    def test_metric_semantics_do_not_overclaim(self) -> None:
        service = self.service(FakeWebsiteAnalyticsHttpFacade())
        service.create_account(plausible_account_payload())
        sync = service.sync("analytics-account-plausible")
        self.assertEqual(sync["status"], "completed")
        breakdown = service.provider_breakdown("content-owned-1")
        totals = breakdown["readmodel"]["totals"]
        self.assertIn("website.average_visit_duration_seconds", totals)
        self.assertNotIn("website.average_read_time_seconds", totals)
        self.assertNotIn("website.engagement_rate", totals)


if __name__ == "__main__":
    unittest.main()
