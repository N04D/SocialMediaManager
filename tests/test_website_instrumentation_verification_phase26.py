from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.website_analytics.scenarios import plausible_account_payload
from integrations.website_instrumentation.scenarios import default_snapshot_payload, instrumentation_config_payload
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.core.website_instrumentation.manifests import build_manifest
from src.core.website_instrumentation.renderer import render_static_page
from src.core.website_instrumentation.service import WebsiteInstrumentationService
from src.core.website_instrumentation.verification import WebsiteInstrumentationVerifier, provider_observed_status


class WebsiteInstrumentationVerificationPhase26Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "owned.sqlite3"
        self.service = WebsiteInstrumentationService(database_path=self.database)
        self.config = self.service.create_config(instrumentation_config_payload())["config"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_static_verification_quality_and_mapping_drift(self) -> None:
        analytics = WebsiteAnalyticsService(database_path=self.database)
        analytics.create_account(plausible_account_payload())
        analytics.put_mappings(
            "analytics-account-plausible",
            [
                {"provider_event_name": "SMM CTA Click", "internal_event_type": "cta_click"},
                {"provider_event_name": "SMM Outbound Click", "internal_event_type": "outbound_click"},
                {"provider_event_name": "SMM Conversion", "internal_event_type": "conversion"},
            ],
        )
        result = self.service.verify(self.config["id"])
        self.assertEqual(result["verification"]["status"], "complete")
        self.assertEqual(result["drift"]["status"], "aligned")
        self.assertIn(result["quality"]["overall_status"], {"partial", "complete"})
        manifest = build_manifest(self.service.repository.get_config(self.config["id"]), default_snapshot_payload())
        bad = render_static_page(manifest, duplicate_runtime=True).replace(manifest.checksum, "wrong")
        static = WebsiteInstrumentationVerifier().verify_static_page(manifest, bad)
        self.assertEqual(static["status"], "misconfigured")
        self.assertTrue(static["duplicate_runtime"])

    def test_provider_observed_levels_are_not_overclaimed(self) -> None:
        manifest = build_manifest(self.service.repository.get_config(self.config["id"]), default_snapshot_payload())
        expected = manifest.expected_events
        self.assertEqual(provider_observed_status(expected, set()), "insufficient_data")
        self.assertEqual(provider_observed_status(expected, {"SMM CTA Click"}), "partially_observed")
        self.assertEqual(
            provider_observed_status(expected, {"SMM CTA Click", "SMM Outbound Click", "SMM Conversion"}),
            "observed",
        )


if __name__ == "__main__":
    unittest.main()
