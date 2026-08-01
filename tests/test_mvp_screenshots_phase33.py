from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPScreenshotsPhase33Tests(Phase33UITestCase):
    def test_screenshot_certification_routes_are_synthetic_and_stable(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        routes = (
            "/home",
            "/setup",
            f"/setup/{session_id}/host_preflight",
            f"/setup/{session_id}/website_account",
            "/content/phase33-fixture/compose",
            f"/setup/{session_id}/review",
            f"/setup/{session_id}/publish",
            f"/setup/{session_id}/result",
            f"/setup/{session_id}/funnel",
        )
        for route in routes:
            html = self.assert_html_contains(route, "SocialMediaManager")
            self.assert_no_sensitive_fixture_data(html)

    def test_blocked_uncertain_conflict_states_have_named_ui(self) -> None:
        self.assert_html_contains("/content/phase33-fixture/compose", "Conflict detected")
        self.assert_html_contains("/home", "Needs attention")
        result = self.complete_demo()
        self.assert_html_contains(f"/setup/{result['payload']['session']['id']}/result", "Recovery")


if __name__ == "__main__":
    import unittest

    unittest.main()
