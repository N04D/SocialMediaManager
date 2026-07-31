from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPFunnelUIPhase33Tests(Phase33UITestCase):
    def test_fixture_metrics_attribution_freshness_and_quality(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        html = self.assert_html_contains(
            f"/setup/{session_id}/funnel",
            "Website Page Views",
            "Visitors",
            "CTA Clicks",
            "Conversions",
            "Mastodon Attributed Visits",
            "Attribution Coverage",
            "Data Freshness",
            "Quality",
        )
        self.assertIn("12", html)

    def test_missing_metrics_are_explicit_not_zero(self) -> None:
        session_id = self.start_demo_via_ui()
        html = self.assert_html_contains(f"/setup/{session_id}/funnel", "Not configured", "Not collected")
        self.assertIn("Provider pending", html)
        self.assertIn("Unsupported", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
