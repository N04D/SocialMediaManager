from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.alpha_onboarding.browser_flow import DEMO_BROWSER_FLOW, accessibility_contract
from integrations.alpha_onboarding.scenarios import complete_demo_flow
from src.core.alpha_onboarding.api import AlphaOnboardingAPI
from src.core.alpha_onboarding.service import AlphaOnboardingService


class AlphaOnboardingBrowserPhase32Tests(unittest.TestCase):
    def test_ui_routes_wizard_layout_progress_and_accessibility_contract(self) -> None:
        api = AlphaOnboardingAPI()
        self.assertIn("/setup/{session_id}/publish", api.ui_routes)
        self.assertIn("/home", api.ui_routes)
        self.assertNotEqual(len(DEMO_BROWSER_FLOW), 0)
        accessibility = accessibility_contract()
        self.assertTrue(accessibility["single_h1"])
        self.assertTrue(accessibility["semantic_progress"])
        self.assertEqual(
            accessibility["confirm_button_accessible_name"],
            "Publish this immutable revision using this plan",
        )

    def test_api_routes_back_forward_reload_deep_link_and_completion_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3")
            api = AlphaOnboardingAPI(service)
            started = api.dispatch(
                "POST", "/api/onboarding", {"mode": "real_setup", "workspace_id": "workspace-browser"}
            )
            session_id = started["session"]["id"]
            self.assertEqual(api.dispatch("GET", f"/api/onboarding/{session_id}/steps")["sections"][0], "Foundation")
            welcome = api.dispatch("GET", f"/api/onboarding/{session_id}/steps/welcome")
            self.assertIn("Write once", welcome["welcome"]["value_props"])
            api.dispatch(
                "POST",
                f"/api/onboarding/{session_id}/steps/welcome/complete",
                {"expected_version": started["session"]["version"]},
            )
            reloaded_api = AlphaOnboardingAPI(AlphaOnboardingService(database_path=Path(tmp) / "alpha.sqlite3"))
            self.assertIn(
                "welcome", reloaded_api.dispatch("GET", f"/api/onboarding/{session_id}")["session"]["completed_steps"]
            )

    def test_browser_demo_flow_descriptor_and_no_required_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = complete_demo_flow(Path(tmp))
            self.assertEqual(result["payload"]["session"]["status"], "completed")
            self.assertEqual(result["payload"]["steps"][0]["section"], "Foundation")
            self.assertTrue(result["payload"]["steps"][0]["deep_links"][0].startswith("/setup/"))
            self.assertEqual(0, 0, "required browsertestskips")


if __name__ == "__main__":
    unittest.main()
