from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.staging_analytics.scenarios import staging_profile_payload
from src.core.staging_analytics.service import StagingAnalyticsCertificationService
from src.core.staging_analytics.worker import StagingAnalyticsCertificationWorker


class StagingAnalyticsSupportBundlePhase27Tests(unittest.TestCase):
    def test_support_bundle_redaction_worker_and_operations_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = StagingAnalyticsCertificationService(database_path=Path(tmp) / "owned.sqlite3")
            service.create_profile(staging_profile_payload())
            worker = StagingAnalyticsCertificationWorker(service)
            result = worker.run_once()
            self.assertEqual(result["backend_provider_writes"], 0)
            health = service.operations_health()
            self.assertGreaterEqual(health["enabled_staging_profiles"], 1)
            bundle = service.support_bundle()["bundle"]
            text = str(bundle).lower()
            self.assertFalse(bundle["manifest"]["forbidden_data_included"])
            for forbidden in (
                "authorization",
                "cookie",
                "request body",
                "event payload",
                "content/drafts",
                "database file",
            ):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
