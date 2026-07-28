from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.staging_analytics.scenarios import staging_profile_payload
from src.core.staging_analytics import (
    PROVIDER_OBSERVED_RECONCILIATION_CONTRACT_VERSION,
    STAGING_ANALYTICS_CERTIFICATION_VERSION,
    STAGING_ANALYTICS_PROFILE_CONTRACT_VERSION,
    STAGING_ANALYTICS_RUN_CONTRACT_VERSION,
    STAGING_BROWSER_EVIDENCE_CONTRACT_VERSION,
    STAGING_CERTIFICATION_REPORT_CONTRACT_VERSION,
    StagingAnalyticsCertificationService,
)
from src.core.staging_analytics.errors import StagingAnalyticsError


class StagingAnalyticsFrameworkPhase27Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = StagingAnalyticsCertificationService(database_path=Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_contracts_profile_origin_account_and_synthetic_page(self) -> None:
        self.assertEqual(STAGING_ANALYTICS_CERTIFICATION_VERSION, "0.1.0")
        self.assertEqual(STAGING_ANALYTICS_PROFILE_CONTRACT_VERSION, "1.0")
        self.assertEqual(STAGING_ANALYTICS_RUN_CONTRACT_VERSION, "1.0")
        self.assertEqual(STAGING_BROWSER_EVIDENCE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PROVIDER_OBSERVED_RECONCILIATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(STAGING_CERTIFICATION_REPORT_CONTRACT_VERSION, "1.0")
        origins = self.service.origins()["origins"]
        self.assertTrue(any(item["environment"] == "staging" and item["synthetic_only"] for item in origins))
        pages = self.service.synthetic_pages()["profiles"]
        self.assertEqual(pages[0]["synthetic_marker"], "true")
        profile = self.service.create_profile(staging_profile_payload())["profile"]
        self.assertEqual(profile["analytics_account_id"], "analytics-account-plausible")
        self.assertTrue(self.service.validate_profile(profile["id"])["valid"])

    def test_production_origin_and_account_are_blocked(self) -> None:
        with self.assertRaises(StagingAnalyticsError):
            self.service.create_profile(
                staging_profile_payload() | {"id": "prod-origin", "staging_origin_reference_id": "prod-origin-blocked"}
            )
        with self.assertRaises(StagingAnalyticsError):
            self.service.create_profile(
                staging_profile_payload()
                | {"id": "prod-account", "analytics_account_id": "analytics-account-production"}
            )

    def test_run_is_immutable_opaque_and_dry_run_by_default(self) -> None:
        self.service.create_profile(staging_profile_payload())
        run = self.service.create_run("staging-cert-profile-1", idempotency_key="same")["run"]
        self.assertEqual(run["status"], "prepared")
        self.assertTrue(run["run_id"].startswith("smm_synthetic_run_"))
        self.assertTrue(run["page_url_reference"].endswith("/synthetic/analytics-smoke"))
        self.assertEqual(self.service.polling_plan("staging-cert-profile-1", run["id"])["delays"], (1, 2, 4, 8))
        self.assertEqual(
            self.service.report(run["id"])["report"]["provider_observed_status"],
            "staging_provider_certification_not_run",
        )


if __name__ == "__main__":
    unittest.main()
