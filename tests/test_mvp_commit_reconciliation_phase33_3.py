from __future__ import annotations

import subprocess

from tests.phase333_support import Phase333TestCase


class MVPCommitReconciliationPhase333Tests(Phase333TestCase):
    def test_existing_repository_subsequent_commit_has_parent_and_keeps_previous_article(self) -> None:
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            first_session = self.prepare_publication(
                repo, port, title="MVP Dogfood Publication 333 A", slug="mvp-dogfood-publication-333-a"
            )
            first = self.publish_session(first_session)
            first_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
            ).stdout.strip()
            second_session = self.prepare_publication(
                repo, port, title="MVP Dogfood Publication 333 B", slug="mvp-dogfood-publication-333-b"
            )
            second = self.publish_session(second_session)

        second_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD^"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        self.assertEqual(parent, first_commit)
        self.assertNotEqual(first_commit, second_commit)
        self.assertIn("repository_state_before:existing", second["mutation_summary"])
        self.assertIn("parent_commit:" + first_commit, second["mutation_summary"])
        self.assertEqual(first["verification_status"], "publication_verified")
        self.assertEqual(second["verification_status"], "publication_verified")
        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-333-a.md").exists())
        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-333-b.md").exists())
