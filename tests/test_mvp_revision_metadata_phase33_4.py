from __future__ import annotations

import mvp_dashboard
from tests.phase334_support import Phase334TestCase


class MVPRevisionMetadataPhase334Tests(Phase334TestCase):
    def test_revision_and_review_bind_custom_seo_description(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id, draft_id = self.prepare_publication_with_custom_seo(repo, port)
            publication = mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
            revision = mvp_dashboard.owned_service().repository.get_revision(publication["content_revision_id"])
            page = self.page(f"/content/{draft_id}/compose?setup_session={session_id}")

        self.assertEqual(revision.content_item_id, draft_id)
        self.assertEqual(revision.seo_description, self.custom_seo)
        self.assertEqual(publication["checksum_bindings"]["seo_description"], self.custom_seo)
        self.assertEqual(publication["checksum_bindings"]["seo_description_source"], "custom")
        self.assertIn("SEO description", page)
        self.assertIn(self.custom_seo, page)

        self.autosave(draft_id, 2, seo_description="Later draft change")
        unchanged = mvp_dashboard.owned_service().repository.get_revision(revision.id)
        self.assertEqual(unchanged.seo_description, self.custom_seo)
