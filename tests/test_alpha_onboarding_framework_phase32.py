from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.alpha_onboarding.scenarios import complete_demo_flow
from src.core.alpha_onboarding.contracts import (
    ALPHA_DEMO_MODE_CONTRACT_VERSION,
    ALPHA_FIRST_PUBLICATION_CONTRACT_VERSION,
    ALPHA_ONBOARDING_FRAMEWORK_VERSION,
    ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION,
    ALPHA_ONBOARDING_STEP_CONTRACT_VERSION,
    ALPHA_SETUP_READINESS_CONTRACT_VERSION,
)
from src.core.alpha_onboarding.errors import AlphaOnboardingError
from src.core.alpha_onboarding.service import AlphaOnboardingService
from src.core.alpha_onboarding.steps import OPTIONAL_STEPS, REQUIRED_STEPS, STEP_ORDER, step_registry


class AlphaOnboardingFrameworkPhase32Tests(unittest.TestCase):
    def service(self, tmp: str) -> AlphaOnboardingService:
        return AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")

    def test_contract_versions_and_step_registry(self) -> None:
        self.assertEqual(ALPHA_ONBOARDING_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION, "1.0")
        self.assertEqual(ALPHA_ONBOARDING_STEP_CONTRACT_VERSION, "1.0")
        self.assertEqual(ALPHA_SETUP_READINESS_CONTRACT_VERSION, "1.0")
        self.assertEqual(ALPHA_FIRST_PUBLICATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(ALPHA_DEMO_MODE_CONTRACT_VERSION, "1.0")
        registry = step_registry()
        self.assertEqual(tuple(registry), STEP_ORDER)
        self.assertTrue(REQUIRED_STEPS <= set(registry))
        self.assertTrue(OPTIONAL_STEPS <= set(registry))
        self.assertFalse(registry["analytics_account"].required)
        self.assertTrue(step_registry(analytics_configured=True)["instrumentation"].required)

    def test_session_create_resume_cancel_conflict_duplicate_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            created = service.start(workspace_id="workspace-a", idempotency_key="a")
            session_id = created["session"]["id"]
            self.assertEqual(created["session"]["status"], "in_progress")
            self.assertEqual(service.resume(session_id)["session"]["id"], session_id)
            with self.assertRaises(AlphaOnboardingError) as duplicate:
                service.start(workspace_id="workspace-a", idempotency_key="b")
            self.assertEqual(duplicate.exception.status_code, 409)
            stale = created["session"]["version"]
            service.complete_step(session_id, "welcome", {"expected_version": stale})
            with self.assertRaises(AlphaOnboardingError) as conflict:
                service.cancel(session_id, expected_version=stale)
            self.assertEqual(conflict.exception.status_code, 409)
            restarted = self.service(tmp)
            self.assertIn("welcome", restarted.get(session_id)["session"]["completed_steps"])

    def test_step_dependencies_optional_skip_and_resource_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            session_id = service.start(workspace_id="workspace-b", idempotency_key="b")["session"]["id"]
            with self.assertRaises(AlphaOnboardingError):
                service.complete_step(session_id, "website_account")
            service.complete_step(
                session_id, "welcome", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            service.complete_step(
                session_id, "host_preflight", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            service.complete_step(
                session_id, "workspace", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            service.complete_step(
                session_id, "operator_identity", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            service.complete_step(
                session_id,
                "publication_destination",
                {"expected_version": service.get(session_id)["session"]["version"]},
            )
            payload = service.complete_step(
                session_id, "website_account", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            self.assertIn("website_account", payload["session"]["completed_steps"])
            self.assertTrue(any(item["resource_type"] == "website_account" for item in payload["bindings"]))
            skipped = service.skip_step(
                session_id, "analytics_account", {"expected_version": payload["session"]["version"]}
            )
            self.assertIn("analytics_account", skipped["session"]["skipped_optional_steps"])
            with self.assertRaises(AlphaOnboardingError):
                service.skip_step(session_id, "publish", {"expected_version": skipped["session"]["version"]})

    def test_deterministic_demo_full_flow_is_durable_and_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = complete_demo_flow(Path(tmp))
            payload = result["payload"]
            self.assertEqual(payload["session"]["status"], "completed")
            self.assertTrue(payload["readiness"]["alpha_operational_ready"])
            self.assertFalse(payload["readiness"]["production_ready"])
            self.assertFalse(payload["readiness"]["external_plugin_sandbox_ready"])
            self.assertEqual(payload["readiness"]["remote_ci_status"], "artifact_not_imported")
            self.assertEqual(result["funnel"]["metrics"]["website_page_views"], 12)
            self.assertNotIn("content/drafts", str(payload))


if __name__ == "__main__":
    unittest.main()
