from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPResponsivePhase33Tests(Phase33UITestCase):
    def test_desktop_tablet_mobile_layout_rules_and_no_overflow_contract(self) -> None:
        html = self.assert_html_contains("/setup", "@media (max-width: 900px)", "mobile-nav", "grid-template-columns")
        self.assertIn("minmax(0,1fr)", html)
        self.assertNotIn("width:100vw", html)

    def test_mobile_setup_and_composer_keep_primary_action_reachable(self) -> None:
        setup = self.assert_html_contains("/setup", "Start demo")
        composer = self.assert_html_contains("/content/phase33-fixture/compose", "Open composer", "Saved")
        self.assertIn("Connect your website", setup)
        self.assertIn("Markdown editor", composer)


if __name__ == "__main__":
    import unittest

    unittest.main()
