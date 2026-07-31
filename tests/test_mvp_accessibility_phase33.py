from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPAccessibilityPhase33Tests(Phase33UITestCase):
    def test_headings_labels_focus_skip_link_live_regions_and_status_text(self) -> None:
        html = self.assert_html_contains(
            "/content/phase33-fixture/compose",
            "<h1>Compose</h1>",
            "Skip to main content",
            ":focus-visible",
            "<label",
            'aria-live="polite"',
            "status",
        )
        self.assertIn("<nav>", html)

    def test_confirmation_accessible_name_and_error_contract(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        html = self.assert_html_contains(
            f"/setup/{session_id}/review", "Publish this immutable revision using this plan"
        )
        self.assertIn("<button", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
