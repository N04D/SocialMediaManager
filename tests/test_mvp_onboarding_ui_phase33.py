from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPOnboardingUIPhase33Tests(Phase33UITestCase):
    def test_start_resume_required_optional_progress_and_restart(self) -> None:
        session_id = self.start_demo_via_ui()
        html = self.assert_html_contains(
            f"/setup/{session_id}",
            "Setup progress",
            "Alpha readiness",
            "Production readiness",
            "Foundation",
            "Analytics",
            "required",
            "optional",
            "Exit and resume",
        )
        self.assertIn("External plugin sandbox not certified", html)
        self.assertIn("Remote CI artifact not imported", html)

    def test_step_forms_validation_errors_and_secret_input(self) -> None:
        session_id = self.start_demo_via_ui()
        html = self.assert_html_contains(
            f"/setup/{session_id}/managed_secrets",
            'type="password"',
            "never rendered back",
            "expected_version",
            "csrf",
        )
        self.assertNotIn("secret_value=", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
