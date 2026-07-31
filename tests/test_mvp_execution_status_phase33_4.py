from __future__ import annotations

from dataclasses import asdict

import mvp_dashboard
from channels.markdown_website.errors import MarkdownWebsiteGitError
from tests.phase334_support import Phase334TestCase


class MVPExecutionStatusPhase334Tests(Phase334TestCase):
    def test_completed_execution_status_row_is_durable(self) -> None:
        session_id, _repo, publication = self.publish_custom_seo()
        page = self.page(f"/setup/{session_id}/result")

        self.assertIn("Execution status", page)
        self.assertIn("Completed", page)
        self.assertIn("Execution stage", page)
        self.assertIn("Verified", page)
        self.assertIn(publication["execution_request_id"], page)

        service = mvp_dashboard.alpha_ui_service()
        reloaded = asdict(service.repository.first_publication(session_id))
        self.assertEqual(mvp_dashboard._execution_status(reloaded)["status"], "Completed")

    def test_failed_execution_status_shows_stage_and_safe_error(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id, _draft_id = self.prepare_publication_with_custom_seo(repo, port)

            class FailingPublisher:
                def publish(self, *args, **kwargs):
                    raise MarkdownWebsiteGitError("markdown_website.git.closed_alpha_failure", "Safe failure.")

            original = mvp_dashboard.GitPublisher
            mvp_dashboard.GitPublisher = FailingPublisher
            try:
                publication = self.publish_session(session_id)
                page = self.page(f"/setup/{session_id}/result")
            finally:
                mvp_dashboard.GitPublisher = original

        self.assertEqual(mvp_dashboard._execution_status(publication)["status"], "Failed")
        self.assertIn("Execution status", page)
        self.assertIn("Failed", page)
        self.assertIn("Safe error code", page)
        self.assertIn("markdown_website.git.closed_alpha_failure", page)
        self.assertNotIn("publication_verified", publication["verification_status"])

    def test_uncertain_execution_status_requires_reconciliation_action(self) -> None:
        publication = {
            "verification_status": "uncertain",
            "mutation_summary": ("execution_status:uncertain", "stage:git_committing"),
            "evidence_ids": ("evidence-uncertain",),
            "timeline": (
                {
                    "phase": "Git commit",
                    "status": "uncertain",
                    "safe_evidence_summary": "evidence-uncertain",
                    "error_code": "commit_outcome_uncertain",
                },
            ),
        }

        status = mvp_dashboard._execution_status(publication)
        panel = mvp_dashboard._execution_status_panel(status)

        self.assertEqual(status["status"], "Uncertain")
        self.assertIn("read-only reconciliation", panel)
        self.assertNotIn("Retry automatically", panel)
