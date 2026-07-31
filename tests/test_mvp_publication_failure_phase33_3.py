from __future__ import annotations

import mvp_dashboard
from channels.markdown_website.errors import MarkdownWebsiteGitError
from tests.phase333_support import Phase333TestCase


class MVPPublicationFailurePhase333Tests(Phase333TestCase):
    def test_failure_result_page_shows_execution_evidence_and_safe_error(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)

            class FailingPublisher:
                def publish(self, *args, **kwargs):
                    raise MarkdownWebsiteGitError("markdown_website.git.before_commit", "Before commit failure.")

            original = mvp_dashboard.GitPublisher
            mvp_dashboard.GitPublisher = FailingPublisher
            try:
                self.publish_session(session_id)
            finally:
                mvp_dashboard.GitPublisher = original
            page = self.page(f"/setup/{session_id}/result")

        self.assertIn("Execution ID", page)
        self.assertIn("failed", page)
        self.assertIn("safe_error_code:markdown_website.git.before_commit", page)
        self.assertIn("Evidence", page)
