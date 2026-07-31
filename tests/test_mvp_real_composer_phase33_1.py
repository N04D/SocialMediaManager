from __future__ import annotations

from src.core.owned_publication.errors import OwnedPublicationError
from tests.phase331_support import Phase331TestCase


class MVPRealComposerPhase331Tests(Phase331TestCase):
    def test_real_draft_autosave_restart_and_conflict(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        draft_id = self.create_draft_and_plan_after_destination(session_id)
        service = __import__("mvp_dashboard").owned_service()
        draft = service.repository.get_draft(draft_id)
        saved = service.autosave(draft_id, {"expected_version": draft.version, "title": "A edit"})
        self.assertEqual(saved["status"], "saved")
        with self.assertRaises(OwnedPublicationError):
            service.autosave(draft_id, {"expected_version": draft.version, "title": "B stale"})
        self.assertEqual(__import__("mvp_dashboard").owned_service().repository.get_draft(draft_id).title, "A edit")

    def create_draft_and_plan_after_destination(self, session_id: str) -> str:
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            publication = self.create_draft_and_plan(session_id)
        return str(publication["content_item_id"])
