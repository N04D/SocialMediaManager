from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.website_analytics.scenarios import plausible_account_payload
from src.core.website_analytics import (
    PLAUSIBLE_ANALYTICS_ADAPTER_VERSION,
    WEBSITE_ANALYTICS_ACCOUNT_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION,
    WebsiteAnalyticsService,
)
from src.core.website_analytics.errors import WebsiteAnalyticsError
from src.core.website_analytics.sync import WebsiteAnalyticsQueryPlanner


class WebsiteAnalyticsFrameworkPhase25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = WebsiteAnalyticsService(database_path=Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_contracts_provider_identity_and_capabilities(self) -> None:
        self.assertEqual(WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(WEBSITE_ANALYTICS_ACCOUNT_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLAUSIBLE_ANALYTICS_ADAPTER_VERSION, "0.1.0")
        provider = self.service.providers_payload()["providers"][0]
        self.assertEqual(provider["provider_id"], "analytics.plausible")
        self.assertEqual(provider["execution_mode"], "built_in_in_process")
        self.assertEqual(provider["data_access"], "read_only")
        capabilities = {item["name"]: item["status"] for item in provider["capabilities"]}
        for required in {"page_metrics", "visitor_metrics", "traffic_sources", "custom_events", "pagination"}:
            self.assertEqual(capabilities[required], "supported")
        self.assertEqual(self.service.providers_payload()["distribution_path"], "built_in_in_process")

    def test_account_origin_secret_and_concurrency(self) -> None:
        account = self.service.create_account(plausible_account_payload())["account"]
        self.assertEqual(account["secret_reference_id"], "secret-plausible-fixture")
        self.assertNotIn("fixture-token", str(account))
        self.assertTrue(self.service.origin_registry()["host_owned"])
        with self.assertRaises(WebsiteAnalyticsError):
            bad = plausible_account_payload() | {"origin_reference_id": "https://evil.example"}
            self.service.create_account(bad)
        with self.assertRaises(WebsiteAnalyticsError):
            bad = plausible_account_payload() | {"id": "raw-secret-account", "secret_reference_id": "raw:token"}
            self.service.create_account(bad)
        disabled = self.service.enable(account["id"], enabled=False, expected_version=account["version"])["account"]
        self.assertFalse(disabled["enabled"])
        with self.assertRaises(WebsiteAnalyticsError):
            self.service.enable(account["id"], enabled=True, expected_version=account["version"])

    def test_queryplanner_bounds_allowlists_and_no_arbitrary_query(self) -> None:
        account = self.service.create_account(plausible_account_payload())["account"]
        typed = self.service.repository.get_account(account["id"])
        queries = WebsiteAnalyticsQueryPlanner(max_days_per_query=7).plan(typed, sync_type="initial")
        self.assertGreater(len(queries), 3)
        with self.assertRaises(WebsiteAnalyticsError):
            bad = queries[0].__class__(**{**queries[0].__dict__, "metric_keys": ("raw_sql_metric",)})
            WebsiteAnalyticsQueryPlanner().validate_query(bad)
        with self.assertRaises(WebsiteAnalyticsError):
            bad = queries[0].__class__(**{**queries[0].__dict__, "dimensions": ("visit:ip",)})
            WebsiteAnalyticsQueryPlanner().validate_query(bad)


if __name__ == "__main__":
    unittest.main()
