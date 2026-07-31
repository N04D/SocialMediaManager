from __future__ import annotations

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPRealAutosavePhase332Tests(Phase332TestCase):
    def test_single_context_first_and_second_autosave_increment_versions(self) -> None:
        _, draft_id = self.prepared_session_with_draft()
        initial = mvp_dashboard.owned_service().get_content(draft_id)
        self.assertEqual(initial["version"], 1)

        first = self.autosave(
            draft_id, 1, title="MVP Dogfood Publication 332 Saved", slug="mvp-dogfood-publication-332-saved"
        )
        self.assertEqual(first["draft"]["version"], 2)

        second = self.autosave(
            draft_id,
            2,
            markdown_body="# MVP Dogfood Publication 332 Saved\n\nSecond autosave persisted.",
            slug="mvp-dogfood-publication-332-saved",
        )
        self.assertEqual(second["draft"]["version"], 3)

        reloaded = mvp_dashboard.owned_service().get_content(draft_id)
        self.assertEqual(reloaded["draft_id"], draft_id)
        self.assertEqual(reloaded["version"], 3)
        self.assertIn("Second autosave persisted", reloaded["markdown_body"])
        self.assertEqual(reloaded["slug"], "mvp-dogfood-publication-332-saved")
