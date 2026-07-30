from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.alpha_onboarding.models import AlphaOnboardingFinding, utc_now_iso
from src.core.alpha_onboarding.service import AlphaOnboardingService


class AlphaOnboardingRecoveryPhase32Tests(unittest.TestCase):
    def test_guided_recovery_safe_actions_and_blocked_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            session_id = service.start(workspace_id="workspace-recovery", idempotency_key="recovery")["session"]["id"]
            finding = AlphaOnboardingFinding(
                id="finding-repository-dirty",
                session_id=session_id,
                step_id="website_account",
                code="repository_dirty",
                severity="blocking",
                explanation="Repository has uncommitted operator-owned changes.",
                status="open",
                created_at=utc_now_iso(),
            )
            service.repository.replace_findings(session_id, [finding])
            recovery = service.recovery(session_id)["recoveries"][0]
            self.assertIn("retry read-only check", recovery["safe_actions"])
            self.assertIn("force Git operations", recovery["blocked_actions"])
            executed = service.execute_recovery(session_id, "repository_dirty")
            self.assertFalse(executed["mutation_performed"])

    def test_partial_onboarding_restart_existing_resource_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alpha.sqlite3"
            service = AlphaOnboardingService(database_path=db)
            session_id = service.start(workspace_id="workspace-partial", idempotency_key="partial")["session"]["id"]
            for step in (
                "welcome",
                "host_preflight",
                "workspace",
                "operator_identity",
                "publication_destination",
                "website_account",
            ):
                service.complete_step(
                    session_id, step, {"expected_version": service.get(session_id)["session"]["version"]}
                )
            restarted = AlphaOnboardingService(database_path=db)
            payload = restarted.resume(session_id)
            self.assertIn("website_account", payload["session"]["completed_steps"])
            self.assertTrue(any(item["resource_type"] == "website_account" for item in payload["bindings"]))
            self.assertEqual(payload["session"]["current_step"], "managed_secrets")

    def test_failure_findings_cover_required_codes(self) -> None:
        codes = {
            "vault_unavailable",
            "repository_dirty",
            "accountdoctor_failure",
            "missing_secret",
            "approval_pending",
            "renderer_validation",
            "missing_media",
            "publication_uncertain",
            "verification_pending",
            "analytics_not_configured",
            "instrumentation_drift",
            "provider_rate_limited",
            "current_revision_changed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            session_id = service.start(workspace_id="workspace-failures", idempotency_key="failures")["session"]["id"]
            findings = [
                AlphaOnboardingFinding(
                    id="finding-" + code,
                    session_id=session_id,
                    step_id="host_preflight",
                    code=code,
                    severity="blocking" if code != "analytics_not_configured" else "warning",
                    explanation=code,
                    status="open",
                    created_at=utc_now_iso(),
                )
                for code in codes
            ]
            service.repository.replace_findings(session_id, findings)
            readiness = service.readiness(session_id)
            self.assertIn("repository_dirty", readiness.blocking_findings)
            self.assertIn("analytics_not_configured", readiness.warning_findings)


if __name__ == "__main__":
    unittest.main()
