from __future__ import annotations

from tests.phase33_support import Phase33UITestCase, confirmation_text


class MVPPublicationUIPhase33Tests(Phase33UITestCase):
    def test_plan_review_confirmation_and_one_execution(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        review = self.assert_html_contains(
            f"/setup/{session_id}/review",
            "Review your article",
            "Ready to publish",
            "Technical details",
            confirmation_text(),
        )
        self.assertIn("idempotency_key", review)
        self.assertIn("Type Publish to confirm", review)

    def test_timeline_result_warning_uncertain_and_reconciliation(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        timeline = self.assert_html_contains(
            f"/setup/{session_id}/publish",
            "Publishing",
            "Review confirmed",
            "Publishing started",
            "Website saved",
            "Analytics pending",
        )
        self.assertIn("Warning", timeline)
        page = self.assert_html_contains(
            f"/setup/{session_id}/result", "Recovery", "No second publish will be attempted automatically"
        )
        self.assertIn("Technical details", page)


if __name__ == "__main__":
    import unittest

    unittest.main()
