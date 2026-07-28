from __future__ import annotations

import unittest
from pathlib import Path


class StagingAnalyticsSecurityPhase27Tests(unittest.TestCase):
    def test_no_backend_events_api_or_real_content_path(self) -> None:
        files = [
            Path("src/core/staging_analytics/service.py"),
            Path("src/core/staging_analytics/browser.py"),
            Path("src/core/staging_analytics/support_bundle.py"),
        ]
        existing = [path for path in files if path.exists()]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in existing)
        self.assertNotIn("/api/event", combined)
        self.assertNotIn("requests.", combined)
        self.assertNotIn("httpx.", combined)
        self.assertNotIn("socket.socket", combined)
        self.assertNotIn("shell=True", combined)
        self.assertNotIn("content/drafts", combined)
        self.assertIn("production_account_blocked", combined)

    def test_ci_has_required_deterministic_and_optional_staging_jobs(self) -> None:
        workflow = Path(".github/workflows/owned-publication-operations.yml").read_text(encoding="utf-8")
        self.assertIn("Staging Analytics Deterministic Certification", workflow)
        self.assertIn("Staging Analytics Provider Smoke", workflow)
        self.assertIn("execute_staging_provider_smoke", workflow)
        self.assertIn("not_configured", workflow)


if __name__ == "__main__":
    unittest.main()
