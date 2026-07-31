from __future__ import annotations

import subprocess

from tests.phase333_support import Phase333TestCase


class MVPPublicationSecurityPhase333Tests(Phase333TestCase):
    def test_no_push_no_productrepo_no_user_owned_or_broad_staging(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)
            result = self.publish_session(session_id)

        self.assertIn("push:none", result["mutation_summary"])
        self.assertNotIn("content/drafts", str(result))
        self.assertNotIn("secret", str(result).lower())
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo, text=True, capture_output=True)
        self.assertEqual(staged.stdout.strip(), "")
        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-333.md").exists())
