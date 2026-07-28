from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.staging_analytics.scenarios import staging_profile_payload
from src.core.staging_analytics.service import StagingAnalyticsCertificationService


class StagingAnalyticsUncertaintyPhase27Tests(unittest.TestCase):
    def test_uncertain_browser_event_does_not_blind_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = StagingAnalyticsCertificationService(database_path=Path(tmp) / "owned.sqlite3")
            service.create_profile(staging_profile_payload())
            run = service.create_run("staging-cert-profile-1", idempotency_key="uncertain")["run"]
            uncertain = service.mark_uncertain(run["id"])
            self.assertTrue(uncertain["no_blind_retry"])
            self.assertEqual(uncertain["run"]["status"], "browser_mutation_uncertain")
            reconciled = service.reconcile_run(
                run["id"],
                observed_events=[
                    {"event_name": "SMM CTA Click", "smm_synthetic_run_id": run["run_id"]},
                    {"event_name": "SMM Conversion", "smm_synthetic_run_id": run["run_id"]},
                ],
            )
            self.assertEqual(reconciled["run"]["status"], "provider_observed")
            new_run = service.create_run("staging-cert-profile-1", idempotency_key="manual-rerun")["run"]
            self.assertNotEqual(new_run["run_id"], run["run_id"])


if __name__ == "__main__":
    unittest.main()
