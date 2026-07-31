from __future__ import annotations

from tests.phase33_support import Phase33UITestCase, confirmation_text


class MVPPublicationUIPhase33Tests(Phase33UITestCase):
    def test_plan_review_confirmation_and_one_execution(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        review = self.assert_html_contains(
            f"/setup/{session_id}/review",
            "Final review",
            "Immutable revision",
            "External mutations",
            confirmation_text(),
        )
        self.assertIn("idempotency_key", review)
        self.assertIn("Exact confirmation", review)

    def test_timeline_result_warning_uncertain_and_reconciliation(self) -> None:
        result = self.complete_demo()
        session_id = result["payload"]["session"]["id"]
        timeline = self.assert_html_contains(
            f"/setup/{session_id}/publish",
            "Plan confirmed",
            "Website execution claimed",
            "Git commit created",
            "Analytics pending",
        )
        self.assertIn("warning", timeline)
        page = self.assert_html_contains(
            f"/setup/{session_id}/result", "Guided recovery", "Safe actions", "Blocked action"
        )
        self.assertIn("Social publication will not be retried automatically", page)


if __name__ == "__main__":
    import unittest

    unittest.main()
