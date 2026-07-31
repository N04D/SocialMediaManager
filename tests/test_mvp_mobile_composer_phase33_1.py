from __future__ import annotations

from tests.phase331_support import Phase331TestCase


class MVPMobileComposerPhase331Tests(Phase331TestCase):
    def test_mobile_composer_has_no_horizontal_overflow_contract(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            publication = self.create_draft_and_plan(session_id)
        html = self.page(f"/content/{publication['content_item_id']}/compose?setup_session={session_id}")
        self.assertIn("@media (max-width: 900px)", html)
        self.assertIn("overflow-x:hidden", html)
        self.assertIn("max-width:100%", html)
        self.assertNotIn("width:100vw", html)
