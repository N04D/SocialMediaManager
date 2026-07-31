from __future__ import annotations

from pathlib import Path

import mvp_dashboard
from tests.phase331_support import Phase331TestCase


class MVPRealModeSecurityPhase331Tests(Phase331TestCase):
    def test_arbitrary_path_cross_workspace_fixture_and_secret_guards(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        _payload, status = self.post(
            f"/setup/{session_id}/complete",
            {
                "step_id": "publication_destination",
                "display_name": "Traversal",
                "managed_root": str(self.root),
                "repository": "../outside",
                "branch": "main",
                "public_url_template": "http://127.0.0.1:1/articles/{slug}.md",
            },
        )
        self.assertEqual(status, 400)
        with self.assertRaises(ValueError):
            mvp_dashboard._guard_no_fixture({"draft_id": "phase33-fixture"})
        operations = self.page("/operations")
        self.assertIn("External plugin sandbox ready", operations)
        self.assertIn("No", operations)
        self.assertNotIn("secret_value=", operations)

    def test_content_and_drafts_are_not_destination_resources(self) -> None:
        product = Path(__file__).resolve().parents[1]
        for protected in (product / "content", product / "drafts"):
            with self.assertRaises(ValueError):
                mvp_dashboard._block_protected_destination(protected)
