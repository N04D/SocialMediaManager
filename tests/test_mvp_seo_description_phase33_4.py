from __future__ import annotations

import mvp_dashboard
from tests.phase334_support import Phase334TestCase


class MVPSeoDescriptionPhase334Tests(Phase334TestCase):
    def test_custom_seo_description_autosaves_reloads_and_survives_service_restart(self) -> None:
        session_id, draft_id = self.prepared_session_with_draft()
        custom = "Custom SEO description survives autosave reload and restart."

        saved = self.autosave(draft_id, 1, seo_description=custom, summary="Fallback summary")
        self.assertEqual(saved["draft"]["seo_description"], custom)
        self.assertEqual(saved["draft"]["version"], 2)

        api = mvp_dashboard.owned_service().get_content(draft_id)
        self.assertEqual(api["seo_description"], custom)
        self.assertEqual(api["metadata"]["seo_description"], custom)

        mvp_dashboard.MVP_DATABASE = self.database_path
        restarted = mvp_dashboard.owned_service().get_content(draft_id)
        self.assertEqual(restarted["seo_description"], custom)

        page = self.page(f"/content/{draft_id}/compose?setup_session={session_id}")
        self.assertIn(custom, page)

    def test_empty_seo_description_uses_summary_fallback_only_when_custom_absent(self) -> None:
        self.assertEqual(
            mvp_dashboard._seo_description_for_publication("", "Useful fallback summary", "Body text."),
            "Useful fallback summary",
        )
        self.assertEqual(
            mvp_dashboard._seo_description_source("", "Useful fallback summary"),
            "summary",
        )
        self.assertEqual(
            mvp_dashboard._seo_description_for_publication(" Custom wins ", "Fallback summary", "Body text."),
            "Custom wins",
        )
        self.assertEqual(mvp_dashboard._seo_description_source("Custom wins", "Fallback summary"), "custom")
