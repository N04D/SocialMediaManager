from __future__ import annotations

import mvp_dashboard
from channels.markdown_website.errors import MarkdownWebsiteGitError
from tests.phase333_support import Phase333TestCase


class MVPExecutionDurabilityPhase333Tests(Phase333TestCase):
    def test_execution_id_exists_before_publisher_failure_is_recorded(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)

            class FailingPublisher:
                def publish(self, *args, **kwargs):
                    raise MarkdownWebsiteGitError("markdown_website.git.injected_failure", "Injected safe failure.")

            original = mvp_dashboard.GitPublisher
            mvp_dashboard.GitPublisher = FailingPublisher
            try:
                result = self.publish_session(session_id)
            finally:
                mvp_dashboard.GitPublisher = original

        self.assertTrue(result["execution_request_id"])
        self.assertEqual(result["verification_status"], "failed")
        self.assertIn("commit_created:false", result["mutation_summary"])
        self.assertIn("verification_status:not_started", result["mutation_summary"])
        self.assertNotIn("Git commit created", " ".join(item["phase"] for item in result["timeline"]))
