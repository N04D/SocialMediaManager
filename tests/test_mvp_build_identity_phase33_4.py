from __future__ import annotations

import json

import mvp_dashboard
from tests.phase334_support import Phase334TestCase


class MVPBuildIdentityPhase334Tests(Phase334TestCase):
    def test_health_reports_current_safe_build_identity(self) -> None:
        body = self.page("/health")
        payload = json.loads(body)

        self.assertEqual(payload["application_version"], "phase33.4")
        self.assertEqual(payload["dashboard_contract_version"], "mvp-dashboard-closed-alpha-0.1")
        self.assertIn("commit_sha", payload)
        self.assertIn("started_at", payload)
        self.assertNotIn("dirty", payload)
        self.assertNotIn("content/", body)
        self.assertEqual(mvp_dashboard.APPLICATION_VERSION, "phase33.4")
