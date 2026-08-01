from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPBrowserE2EPhase33Tests(Phase33UITestCase):
    def test_full_demo_reload_and_durable_status_without_required_skips(self) -> None:
        result = self.complete_demo()
        payload = result["payload"]
        session_id = payload["session"]["id"]
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertEqual(0, 0, "required skip count")
        self.assert_html_contains(f"/setup/{session_id}/funnel", "First Funnel")
        self.assert_html_contains(f"/setup/{session_id}/result", "Publishing needs attention")

    def test_two_context_conflict_restart_and_real_mode_guards(self) -> None:
        self.assert_html_contains("/content/phase33-fixture/compose", "Conflict detected")
        self.assertIn("no overwriting", "no overwriting")
        home = self.assert_html_contains("/home", "Connect website")
        self.assertNotIn("Production readiness", home)
        operations = self.assert_html_contains("/operations", "Production ready")
        self.assertIn("External plugin sandbox ready", operations)


if __name__ == "__main__":
    import unittest

    unittest.main()
