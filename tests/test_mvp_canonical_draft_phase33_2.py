from __future__ import annotations

import mvp_dashboard
from src.core.owned_publication.errors import OwnedPublicationError
from tests.phase332_support import Phase332TestCase


class MVPCanonicalDraftPhase332Tests(Phase332TestCase):
    def test_resolver_exact_missing_wrong_workspace_fixture_and_no_fallback(self) -> None:
        session_id, draft_id = self.prepared_session_with_draft()
        session = mvp_dashboard.alpha_ui_service().repository.get_session(session_id)
        resolver = mvp_dashboard.CanonicalDraftResolver(mvp_dashboard.alpha_ui_service())

        draft = resolver.resolve_draft(
            session.workspace_id, draft_id, "real_setup", session_id=session_id, require_binding=True
        )
        self.assertEqual(draft.id, draft_id)
        self.assertEqual(draft.workspace_id, session.workspace_id)

        with self.assertRaises(OwnedPublicationError):
            resolver.resolve_draft(session.workspace_id, "missing-draft", "real_setup")
        with self.assertRaises(OwnedPublicationError):
            resolver.resolve_draft("other-workspace", draft_id, "real_setup")
        with self.assertRaises(OwnedPublicationError):
            resolver.resolve_draft(session.workspace_id, "content-owned-1", "real_setup")

        with self.assertRaises(OwnedPublicationError):
            mvp_dashboard.owned_service().get_content("missing-draft")
