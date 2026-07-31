from __future__ import annotations

import subprocess

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPPublicationIdentityPhase332Tests(Phase332TestCase):
    def test_plan_execution_git_commit_and_local_verification_use_same_revision_chain(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            draft_id = self.create_real_draft(session_id, title="Publication Identity 332")
            self.autosave(
                draft_id, 1, slug="publication-identity-332", markdown_body="# Publication Identity 332\n\nVerified."
            )
            mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
            _, status = self.post(
                f"/setup/{session_id}/confirm",
                {"confirmation": mvp_dashboard.CONFIRMATION_TEXT, "idempotency_key": "phase332-confirm"},
            )
            self.assertEqual(status, 303)
            result = mvp_dashboard._real_publication_status(mvp_dashboard.alpha_ui_service(), session_id)["publication"]

        self.assertEqual(result["content_item_id"], draft_id)
        self.assertTrue(result["publication_plan_id"])
        self.assertTrue(result["execution_request_id"])
        self.assertEqual(result["verification_status"], "publication_verified")
        self.assertIn("push:none", result["mutation_summary"])
        self.assertTrue((repo / "articles" / "publication-identity-332.md").exists())
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True)
        self.assertIn(commit.stdout.strip(), " ".join(result["mutation_summary"]))
