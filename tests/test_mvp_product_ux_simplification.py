from __future__ import annotations

from pathlib import Path

from tests.phase334_support import Phase334TestCase


class MVPProductUXSimplificationTests(Phase334TestCase):
    def test_primary_navigation_is_collapsed_to_four_product_areas(self) -> None:
        home = self.page("/home")
        self.assertIn("New article", home)
        self.assertIn("Recent content", home)
        self.assertIn("Performance", home)
        self.assertIn('href="/home"', home)
        self.assertIn('href="/content"', home)
        self.assertIn('href="/analytics"', home)
        self.assertIn("Settings", home)
        self.assertNotIn('href="/calendar"', home)
        self.assertNotIn('href="/operations"', home)
        self.assertNotIn('href="/content/new"', home)
        self.assertNotIn("Production readiness", home)
        self.assertNotIn("External plugin sandbox not certified", home)
        self.assertNotIn("Remote CI artifact not imported", home)

        settings = self.page("/settings")
        self.assertIn("Publishing", settings)
        self.assertIn("Channels", settings)
        self.assertIn("Analytics", settings)
        self.assertIn("Account", settings)
        self.assertIn("Advanced operations", settings)

        operations = self.page("/operations")
        self.assertIn("Production ready", operations)
        self.assertIn("External plugin sandbox ready", operations)
        self.assertIn("CI certification ready", operations)

    def test_content_new_opens_composer_without_setup_pages_for_returning_user(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        payload, status = self.post(
            "/content/new", {"setup_session": session_id, "idempotency_key": "product-ux-new-article"}
        )
        self.assertEqual(status, 303)
        self.assertIn("/content/", payload)
        self.assertIn("/compose", payload)
        self.assertNotIn("/setup/", payload)

    def test_real_composer_centers_writing_and_moves_ids_to_technical_details(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        draft_id = self.create_real_draft(session_id, title="Product UX Article")
        composer = self.page(f"/content/{draft_id}/compose?setup_session={session_id}")
        self.assertIn("Article editor", composer)
        self.assertIn("Preview", composer)
        self.assertIn("Website", composer)
        self.assertIn("SEO & settings", composer)
        self.assertIn("Publish", composer)
        self.assertIn("Technical details", composer)
        self.assertIn("Route draft ID", composer)
        self.assertNotIn("Continue to publication plan", composer)
        self.assertNotIn("Create version", composer)

    def test_review_publish_and_result_are_integrated_into_composer(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id, draft_id = self.prepare_publication_with_custom_seo(repo, port)
            review_legacy = self.page(f"/setup/{session_id}/review")
            self.assertIn("Article editor", review_legacy)
            self.assertIn("Ready to publish", review_legacy)
            self.assertNotIn("Final Review", review_legacy)

            publication = self.publish_session(session_id)
            timeline_legacy = self.page(f"/setup/{session_id}/publish")
            self.assertIn("Published", timeline_legacy)
            self.assertIn("View article", timeline_legacy)
            self.assertNotIn("Publication Timeline", timeline_legacy)

            result = self.page(f"/content/{draft_id}/compose?setup_session={session_id}")
            self.assertIn("Published", result)
            self.assertIn("Your article is live", result)
            self.assertIn("View article", result)
            self.assertIn("Technical details", result)
            self.assertIn(publication["execution_request_id"], result)

        self.assertTrue(Path(repo).exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
