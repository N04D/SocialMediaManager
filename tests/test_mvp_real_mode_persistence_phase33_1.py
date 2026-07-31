from __future__ import annotations

import mvp_dashboard
from tests.phase331_support import Phase331TestCase


class MVPRealModePersistencePhase331Tests(Phase331TestCase):
    def test_real_session_survives_service_recomposition(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            publication = self.create_draft_and_plan(session_id)
        service_after_restart = mvp_dashboard.alpha_ui_service()
        resumed = service_after_restart.get(session_id)
        self.assertEqual(resumed["session"]["id"], session_id)
        bindings = {item["resource_type"]: item["resource_id"] for item in resumed["bindings"]}
        self.assertEqual(bindings["draft_id"], publication["content_item_id"])
        self.assertEqual(bindings["publication_plan_id"], publication["publication_plan_id"])
        self.assertNotIn("Safe Error", self.page(f"/setup/{session_id}"))

    def test_no_duplicate_resources_after_repeated_plan_action(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            first = self.create_draft_and_plan(session_id)
            second = mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
        self.assertEqual(first["publication_plan_id"], second["publication_plan_id"])
