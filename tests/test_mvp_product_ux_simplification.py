from __future__ import annotations

from pathlib import Path

from tests.phase334_support import Phase334TestCase


class MVPProductUXSimplificationTests(Phase334TestCase):
    def test_home_is_action_oriented_and_system_status_moves_to_operations(self) -> None:
        home = self.page("/home")
        self.assertIn("New article", home)
        self.assertIn("Recent content", home)
        self.assertIn("Needs attention", home)
        self.assertIn("Performance snapshot", home)
        self.assertIn("Settings", home)
        self.assertIn("Operations", home)
        self.assertNotIn("Production readiness", home)
        self.assertNotIn("External plugin sandbox not certified", home)
        self.assertNotIn("Remote CI artifact not imported", home)

        operations = self.page("/operations")
        self.assertIn("Production ready", operations)
        self.assertIn("External plugin sandbox ready", operations)
        self.assertIn("CI certification ready", operations)

    def test_real_composer_centers_writing_and_moves_ids_to_technical_details(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        draft_id = self.create_real_draft(session_id, title="Product UX Article")

        composer = self.page(f"/content/{draft_id}/compose?setup_session={session_id}")
        self.assertIn("Article editor", composer)
        self.assertIn("Preview", composer)
        self.assertIn("Website", composer)
        self.assertIn("SEO & settings", composer)
        self.assertIn("Technical details", composer)
        self.assertIn("Route draft ID", composer)

    def test_review_publish_and_result_use_product_language_with_technical_disclosure(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id, _draft_id = self.prepare_publication_with_custom_seo(repo, port)
            review = self.page(f"/setup/{session_id}/review")
            self.assertIn("Review your article", review)
            self.assertIn("Ready to publish", review)
            self.assertIn("Type Publish to confirm", review)
            self.assertIn("Technical details", review)
            self.assertIn("Publication plan ID", review)

            publication = self.publish_session(session_id)
            timeline = self.page(f"/setup/{session_id}/publish")
            self.assertIn("Publishing", timeline)
            self.assertIn("Preparing article", timeline)
            self.assertIn("Website saved", timeline)

            result = self.page(f"/setup/{session_id}/result")
            self.assertIn("Published", result)
            self.assertIn("Your article is live", result)
            self.assertIn("View article", result)
            self.assertIn("Technical details", result)
            self.assertIn(publication["execution_request_id"], result)

        self.assertTrue(Path(repo).exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
