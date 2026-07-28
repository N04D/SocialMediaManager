from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import dashboard
from integrations.website_analytics.fake_provider import FakeWebsiteAnalyticsHttpFacade
from integrations.website_analytics.scenarios import plausible_account_payload
from src.core.website_analytics.errors import WebsiteAnalyticsError
from src.core.website_analytics.service import WebsiteAnalyticsService


class WebsiteAnalyticsSecurityPhase25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_provider_write_path_direct_http_or_raw_secret(self) -> None:
        facade = FakeWebsiteAnalyticsHttpFacade()
        service = WebsiteAnalyticsService(database_path=Path(self.tmp.name) / "owned.sqlite3", http_facade=facade)
        service.create_account(plausible_account_payload())
        service.sync("analytics-account-plausible")
        self.assertEqual(facade.provider_writes, 0)
        source = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in [
                "src/core/website_analytics/service.py",
                "src/providers/analytics/plausible/provider.py",
                "src/providers/analytics/plausible/client.py",
            ]
        )
        for forbidden in ("requests.", "httpx.", "urllib.", "socket.socket", "/api/event"):
            if forbidden == "/api/event":
                self.assertIn("FORBIDDEN_WRITE_ENDPOINTS", source)
            else:
                self.assertNotIn(forbidden, source)
        self.assertNotIn("fixture-token", json.dumps(service.account("analytics-account-plausible")))
        with self.assertRaises(WebsiteAnalyticsError):
            service.create_account(plausible_account_payload() | {"id": "bad-url", "origin_reference_id": "arbitrary"})

    def test_dashboard_api_and_operations_health_do_not_expose_credentials(self) -> None:
        html = dashboard.render_website_analytics_page()
        self.assertIn("Website Analytics Providers", html)
        self.assertNotIn("fixture-token", html)
        service = WebsiteAnalyticsService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        service.create_account(plausible_account_payload())
        health = service.analytics_health()
        self.assertTrue(health["publishing_ready"])
        self.assertIn("analytics_ready", health)


if __name__ == "__main__":
    unittest.main()
