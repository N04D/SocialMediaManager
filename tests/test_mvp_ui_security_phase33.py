from __future__ import annotations

from pathlib import Path

from tests.phase33_support import Phase33UITestCase


class MVPUISecurityPhase33Tests(Phase33UITestCase):
    def test_no_secret_dom_no_token_screenshot_no_user_owned_fixture(self) -> None:
        pages = [
            self.assert_html_contains("/setup", "Start demo"),
            self.assert_html_contains("/content/phase33-fixture/compose", "Synthetic dogfood article"),
        ]
        for html in pages:
            self.assert_no_sensitive_fixture_data(html)
            self.assertNotIn("secret-reference-password", html)

    def test_no_direct_provider_calls_ui_only_mutation_or_false_production_claim(self) -> None:
        source = Path("mvp_dashboard.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "requests.",
            "httpx.",
            "socket.socket",
            "os.system",
            "shell=true",
            "git clean",
            "reset --hard",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("production_ready=true", source)
        self.assertIn("AlphaOnboardingAPI", Path("mvp_dashboard.py").read_text(encoding="utf-8"))

    def test_phase20_remote_ci_and_user_owned_guards(self) -> None:
        result = self.complete_demo()
        readiness = result["payload"]["readiness"]
        self.assertFalse(readiness["external_plugin_sandbox_ready"])
        self.assertFalse(readiness["production_ready"])
        self.assertEqual(readiness["remote_ci_status"], "artifact_not_imported")
        self.assert_no_sensitive_fixture_data(str(result))


if __name__ == "__main__":
    import unittest

    unittest.main()
