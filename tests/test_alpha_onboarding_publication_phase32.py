from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.alpha_onboarding.errors import AlphaOnboardingError
from src.core.alpha_onboarding.service import AlphaOnboardingService


class AlphaOnboardingPublicationPhase32Tests(unittest.TestCase):
    def _ready_service(self, tmp: str) -> tuple[AlphaOnboardingService, str]:
        service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
        session_id = service.start(mode="deterministic_demo", workspace_id="workspace-pub", idempotency_key="pub")[
            "session"
        ]["id"]
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
            service.complete_step(session_id, step, {"expected_version": service.get(session_id)["session"]["version"]})
        return service, session_id

    def test_immutable_revision_variants_snapshots_plan_and_mutation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, session_id = self._ready_service(tmp)
            review = service.publication_review(session_id)
            publication = review["publication"]
            self.assertIn("Git commit", review["mutation_summary"])
            self.assertTrue(publication["content_revision_id"].startswith("revision-alpha-"))
            self.assertTrue(publication["publication_plan_id"].startswith("plan-alpha"))
            self.assertIn("content_revision", publication["checksum_bindings"])
            self.assertEqual(review["requires_confirmation_text"], "Publish this immutable revision using this plan")

    def test_explicit_confirmation_duplicate_click_safe_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, session_id = self._ready_service(tmp)
            with self.assertRaises(AlphaOnboardingError):
                service.publication_confirm(session_id, {"confirmation": "publish"})
            confirmed = service.publication_confirm(
                session_id,
                {"confirmation": "Publish this immutable revision using this plan"},
            )
            second = service.publication_confirm(
                session_id,
                {"confirmation": "Publish this immutable revision using this plan"},
            )
            self.assertTrue(confirmed["execution_started"])
            self.assertFalse(second["execution_started"])
            self.assertTrue(second["duplicate_click_safe"])
            self.assertEqual(service.publication_status(session_id)["publication"]["verification_status"], "verified")
            self.assertFalse(service.publication_status(session_id)["uncertain_blind_retry"])

    def test_scheduling_status_dependency_and_social_release_are_coordinated_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, session_id = self._ready_service(tmp)
            service.complete_step(
                session_id, "social_channels", {"expected_version": service.get(session_id)["session"]["version"]}
            )
            plan = service.publication_review(session_id)
            self.assertIn("Mastodon post if selected", plan["mutation_summary"])
            self.assertIn("Professional social post if selected", plan["mutation_summary"])
            confirmed = service.publication_confirm(
                session_id,
                {"confirmation": "Publish this immutable revision using this plan"},
            )
            self.assertEqual(confirmed["publication"]["timeline"][-1]["phase"], "website_verification")
            self.assertEqual(confirmed["publication"]["timeline"][0]["phase"], "plan_created")


if __name__ == "__main__":
    unittest.main()
