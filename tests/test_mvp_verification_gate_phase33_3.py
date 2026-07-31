from __future__ import annotations

import mvp_dashboard
from channels.markdown_website.errors import MarkdownWebsiteGitError
from tests.phase333_support import Phase333TestCase


class MVPVerificationGatePhase333Tests(Phase333TestCase):
    def test_verification_does_not_start_without_verified_commit(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)

            class FailingPublisher:
                def publish(self, *args, **kwargs):
                    raise MarkdownWebsiteGitError("markdown_website.git.commit_missing", "No commit.")

            original = mvp_dashboard.GitPublisher
            mvp_dashboard.GitPublisher = FailingPublisher
            try:
                result = self.publish_session(session_id)
            finally:
                mvp_dashboard.GitPublisher = original

        self.assertEqual(result["verification_status"], "failed")
        self.assertIn("verification_status:not_started", result["mutation_summary"])
        self.assertIn("Website verification", " ".join(item["phase"] for item in result["timeline"]))
