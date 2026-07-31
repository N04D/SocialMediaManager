from __future__ import annotations

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPRealDraftRestartPhase332Tests(Phase332TestCase):
    def test_restart_keeps_same_draft_id_version_and_next_autosave_succeeds(self) -> None:
        session_id, draft_id = self.prepared_session_with_draft()
        saved = self.autosave(draft_id, 1, title="Restart durable draft")
        version = saved["draft"]["version"]

        service_after_restart = mvp_dashboard.alpha_ui_service()
        session = service_after_restart.repository.get_session(session_id)
        self.assertEqual(mvp_dashboard._bindings(service_after_restart, session_id)["draft_id"], draft_id)
        resolved = mvp_dashboard.CanonicalDraftResolver(service_after_restart).resolve_draft(
            session.workspace_id, draft_id, session.mode, session_id=session_id, require_binding=True
        )
        self.assertEqual(resolved.id, draft_id)
        self.assertEqual(resolved.version, version)

        next_save = mvp_dashboard.owned_service().autosave(
            draft_id,
            {
                "draft_id": draft_id,
                "expected_version": version,
                "title": "Restart durable draft saved again",
                "idempotency_key": "phase332-after-restart",
            },
        )
        self.assertEqual(next_save["draft"]["version"], version + 1)
