from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.staging_analytics.scenarios import staging_profile_payload
from src.core.staging_analytics.service import StagingAnalyticsCertificationService


class StagingAnalyticsBrowserPhase27Tests(unittest.TestCase):
    def test_real_chromium_synthetic_page_consent_and_browser_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = StagingAnalyticsCertificationService(database_path=Path(tmp) / "owned.sqlite3")
            service.create_profile(staging_profile_payload())
            result = service.deterministic_certification("staging-cert-profile-1")
            self.assertTrue(result["deterministic_certification_passed"])
            self.assertFalse(result["staging_provider_certification_passed"])
            self.assertTrue(result["staging_provider_certification_not_run"])
            self.assertEqual(result["backend_provider_writes"], 0)
            evidence = service.evidence(result["run"]["id"])["evidence"]
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all(item["method"] == "BROWSER_CONTEXT" for item in evidence))
            self.assertTrue(all(item["accepted_by_browser_runtime"] for item in evidence))
            self.assertTrue(all("smm_synthetic_run_id" in item["safe_property_names"] for item in evidence))
            self.assertNotIn("event payload", str(evidence).lower())


if __name__ == "__main__":
    unittest.main()
