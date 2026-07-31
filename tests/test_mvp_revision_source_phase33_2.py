from __future__ import annotations

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPRevisionSourcePhase332Tests(Phase332TestCase):
    def test_revision_uses_exact_source_draft_version_content_and_slug(self) -> None:
        session_id, draft_id = self.prepared_session_with_draft()
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
        saved = self.autosave(
            draft_id,
            1,
            title="Revision Source 332",
            slug="revision-source-332",
            markdown_body="# Revision Source 332\n\nExact content.",
        )

        publication = mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
        revision = mvp_dashboard.owned_service().repository.get_revision(publication["content_revision_id"])
        self.assertEqual(revision.content_item_id, draft_id)
        self.assertEqual(revision.source_draft_version, saved["draft"]["version"])
        self.assertEqual(revision.title, "Revision Source 332")
        self.assertEqual(revision.slug, "revision-source-332")
        self.assertIn("Exact content", revision.markdown_body)
