from __future__ import annotations

from mvp_dashboard import is_mvp_get_route, render_mvp_page
from tests.phase33_support import Phase33UITestCase


class MVPDashboardPhase33Tests(Phase33UITestCase):
    def test_shell_navigation_workspace_context_and_home_cards(self) -> None:
        html = self.assert_html_contains(
            "/home",
            "Home",
            "Content",
            "Calendar",
            "Analytics",
            "Setup",
            "Operations",
            "Workspace",
            "Setup status",
            "Alpha readiness",
            "Production readiness",
            "Open blockers",
        )
        self.assert_no_sensitive_fixture_data(html)

    def test_deep_links_and_primary_routes_are_owned_by_mvp_ui(self) -> None:
        for route in ("/", "/home", "/setup", "/content", "/operations"):
            self.assertTrue(is_mvp_get_route(route), route)
        html, status = render_mvp_page("/calendar")
        self.assertEqual(status.value, 200)
        self.assertIn("Publication plan calendar", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
