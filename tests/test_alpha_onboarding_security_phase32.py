from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.alpha_onboarding.fixtures import demo_article
from src.core.alpha_onboarding.api import AlphaOnboardingAPI
from src.core.alpha_onboarding.errors import AlphaOnboardingError
from src.core.alpha_onboarding.mcp import AlphaOnboardingMCP
from src.core.alpha_onboarding.service import AlphaOnboardingService


class AlphaOnboardingSecurityPhase32Tests(unittest.TestCase):
    def test_no_secrets_tokens_private_content_or_user_owned_fixtures(self) -> None:
        article = demo_article()
        self.assertTrue(article["synthetic"])
        self.assertTrue(article["fixture_repository_only"])
        serialized = json.dumps(article).lower()
        self.assertNotIn("token", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("private key", serialized)
        self.assertNotIn("content/drafts", serialized)

    def test_api_cli_mcp_surface_no_direct_channel_or_analytics_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            api = AlphaOnboardingAPI(service)
            self.assertIn("POST /api/onboarding/{id}/publication/confirm", api.routes)
            session_id = service.start(workspace_id="workspace-sec", idempotency_key="sec")["session"]["id"]
            mcp = AlphaOnboardingMCP(service)
            status = mcp.get_alpha_onboarding_status()
            self.assertTrue(status["read_only"])
            sync = service.analytics_sync(session_id)
            self.assertEqual(sync["backend_analytics_event_writes"], 0)
            serialized = json.dumps(service.get(session_id)).lower()
            self.assertNotIn("fixture-token", serialized)
            self.assertNotIn("raw:", serialized)
            self.assertNotIn("private key", serialized)

    def test_real_mode_guards_no_arbitrary_path_no_confirmation_no_blind_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            session_id = service.start(workspace_id="workspace-real", idempotency_key="real")["session"]["id"]
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
            with self.assertRaises(AlphaOnboardingError):
                service.publication_confirm(session_id, {"confirmation": "yes"})
            status = service.publication_status(session_id)
            self.assertFalse(status["uncertain_blind_retry"])
            self.assertNotIn("/home/", json.dumps(service.get(session_id)))
            readiness = service.readiness(session_id)
            self.assertFalse(readiness.production_ready)
            self.assertFalse(readiness.external_plugin_sandbox_ready)


if __name__ == "__main__":
    unittest.main()
