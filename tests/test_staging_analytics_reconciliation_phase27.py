from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.staging_analytics.scenarios import staging_profile_payload
from src.core.staging_analytics.reconciliation import reconcile_provider_observations
from src.core.staging_analytics.service import StagingAnalyticsCertificationService


class StagingAnalyticsReconciliationPhase27Tests(unittest.TestCase):
    def test_partial_delayed_duplicate_and_exact_run_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = StagingAnalyticsCertificationService(database_path=Path(tmp) / "owned.sqlite3")
            service.create_profile(staging_profile_payload())
            run = service.create_run("staging-cert-profile-1", idempotency_key="reconcile")["run"]
            expected = tuple(item["event_name"] for item in run["expected_event_bindings"])
            none = reconcile_provider_observations(run_id=run["run_id"], expected_events=expected, observations=[])
            self.assertEqual(none.quality_status, "not_observed")
            partial = reconcile_provider_observations(
                run_id=run["run_id"],
                expected_events=expected,
                observations=[{"event_name": "SMM CTA Click", "smm_synthetic_run_id": run["run_id"]}],
            )
            self.assertEqual(partial.quality_status, "partially_observed")
            duplicate = reconcile_provider_observations(
                run_id=run["run_id"],
                expected_events=expected,
                observations=[
                    {"event_name": "SMM CTA Click", "smm_synthetic_run_id": run["run_id"]},
                    {"event_name": "SMM CTA Click", "smm_synthetic_run_id": run["run_id"]},
                    {"event_name": "SMM Conversion", "smm_synthetic_run_id": run["run_id"]},
                ],
            )
            self.assertEqual(duplicate.quality_status, "conflicting")
            final = service.reconcile_run(
                run["id"],
                observed_events=[
                    {"event_name": "SMM CTA Click", "smm_synthetic_run_id": run["run_id"]},
                    {"event_name": "SMM Conversion", "smm_synthetic_run_id": run["run_id"]},
                ],
            )
            self.assertIn(final["reconciliation"]["quality_status"], {"observed", "partially_observed"})


if __name__ == "__main__":
    unittest.main()
