from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.alpha_onboarding.service import AlphaOnboardingService


class AlphaOnboardingReadinessPhase32Tests(unittest.TestCase):
    def test_host_preflight_statuses_and_phase20_2_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            checks = service.host_preflight()
            statuses = {check.name: check.status for check in checks}
            self.assertEqual(statuses["database"], "PASS")
            self.assertEqual(statuses["managed secret backend"], "NOT_CONFIGURED")
            self.assertEqual(statuses["phase-20.2 external plugin sandbox"], "FAIL")
            self.assertFalse(
                any(check.blocking for check in checks if check.name == "phase-20.2 external plugin sandbox")
            )

    def test_alpha_ready_not_production_ready_and_optional_analytics_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            session_id = service.start(
                mode="deterministic_demo", workspace_id="workspace-ready", idempotency_key="ready"
            )["session"]["id"]
            for step in (
                "welcome",
                "host_preflight",
                "workspace",
                "operator_identity",
                "publication_destination",
                "website_account",
                "first_content",
                "publication_plan",
                "final_review",
            ):
                service.complete_step(
                    session_id, step, {"expected_version": service.get(session_id)["session"]["version"]}
                )
            service.publication_confirm(session_id, {"confirmation": "Publish this immutable revision using this plan"})
            service.complete_step(
                session_id, "publish", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            service.complete_step(
                session_id, "verification", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            readiness = service.readiness(session_id)
            self.assertTrue(readiness.alpha_operational_ready)
            self.assertTrue(readiness.publishing_ready)
            self.assertEqual(readiness.analytics_status, "not_configured")
            self.assertFalse(readiness.production_ready)
            self.assertFalse(readiness.external_plugin_sandbox_ready)
            self.assertEqual(readiness.remote_ci_status, "artifact_not_imported")

    def test_operations_dashboard_and_support_bundle_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            session_id = service.start(workspace_id="workspace-ops", idempotency_key="ops")["session"]["id"]
            dashboard = service.operations_dashboard()
            self.assertEqual(dashboard["active_onboarding_sessions"], 1)
            self.assertFalse(dashboard["articlebody_as_metric_label"])
            bundle = service.support_bundle_summary(session_id)
            self.assertFalse(bundle["articlebody_included"])
            self.assertFalse(bundle["secrets_included"])
            self.assertFalse(bundle["repository_contents_included"])


if __name__ == "__main__":
    unittest.main()
