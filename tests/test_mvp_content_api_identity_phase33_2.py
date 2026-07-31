from __future__ import annotations

import json

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPContentAPIIdentityPhase332Tests(Phase332TestCase):
    def test_route_id_equals_response_id_and_no_fixture_response(self) -> None:
        _, draft_id = self.prepared_session_with_draft()
        payload = mvp_dashboard.owned_service().get_content(draft_id)

        self.assertEqual(payload["draft_id"], draft_id)
        self.assertEqual(payload["id"], draft_id)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["classification"], "real")
        self.assertNotEqual(payload["draft_id"], "content-owned-1")
        self.assertIn("slug", payload["metadata"])

    def test_route_payload_mismatch_is_blocked(self) -> None:
        _, draft_id = self.prepared_session_with_draft()
        with self.assertRaises(Exception) as ctx:
            mvp_dashboard.owned_service().autosave(
                draft_id,
                {
                    "draft_id": "other-draft",
                    "expected_version": 1,
                    "title": "Wrong route",
                    "idempotency_key": "phase332-mismatch",
                },
            )
        self.assertIn("canonical_draft_identity_mismatch", str(getattr(ctx.exception, "code", ctx.exception)))

    def test_json_payload_contains_no_user_owned_path(self) -> None:
        _, draft_id = self.prepared_session_with_draft()
        payload = json.dumps(mvp_dashboard.owned_service().get_content(draft_id))
        self.assertNotIn("content/drafts", payload)
        self.assertNotIn("Synthetic dogfood article", payload)
