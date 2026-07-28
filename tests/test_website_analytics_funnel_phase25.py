from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.website_analytics.scenarios import plausible_account_payload
from src.core.website_analytics.mcp import WebsiteAnalyticsMCP
from src.core.website_analytics.service import WebsiteAnalyticsService


class WebsiteAnalyticsFunnelPhase25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = WebsiteAnalyticsService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.service.create_account(plausible_account_payload())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_end_to_end_provider_observations_rebuild_funnel_and_mcp(self) -> None:
        self.service.sync("analytics-account-plausible")
        breakdown = self.service.provider_breakdown("content-owned-1")
        self.assertEqual(breakdown["provider"], "analytics.plausible")
        self.assertFalse(breakdown["causality_claimed"])
        totals = breakdown["readmodel"]["totals"]
        self.assertGreater(totals["website.page_views"], 0)
        quality = self.service.quality_report("analytics-account-plausible")["quality"]
        self.assertEqual(quality["status"], "complete")
        mcp = WebsiteAnalyticsMCP(self.service)
        self.assertTrue(mcp.get_website_analytics_accounts()["read_only"])
        self.assertIn("exact_attribution_rate", mcp.explain_attribution("analytics-account-plausible"))


if __name__ == "__main__":
    unittest.main()
