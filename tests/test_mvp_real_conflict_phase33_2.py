from __future__ import annotations

import mvp_dashboard
from src.core.owned_publication.errors import OwnedPublicationError
from tests.phase332_support import Phase332TestCase


class MVPRealConflictPhase332Tests(Phase332TestCase):
    def test_two_context_conflict_then_reload_and_continue(self) -> None:
        _, draft_id = self.prepared_session_with_draft()
        version_a = mvp_dashboard.owned_service().get_content(draft_id)["version"]
        version_b = version_a

        saved = self.autosave(draft_id, version_a, summary="Context A wins")
        self.assertEqual(saved["draft"]["version"], version_a + 1)

        with self.assertRaises(OwnedPublicationError) as ctx:
            self.autosave(draft_id, version_b, summary="Context B stale")
        self.assertEqual(ctx.exception.code, "workspace.conflict")

        current = mvp_dashboard.owned_service().get_content(draft_id)
        self.assertEqual(current["summary"], "Context A wins")
        continued = self.autosave(draft_id, current["version"], summary="Context B after reload")
        self.assertEqual(continued["draft"]["version"], current["version"] + 1)
