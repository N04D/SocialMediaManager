from __future__ import annotations

import subprocess

from tests.phase333_support import Phase333TestCase


class MVPFirstGitCommitPhase333Tests(Phase333TestCase):
    def test_empty_repository_creates_first_commit_and_verifies_local_url(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)
            result = self.publish_session(session_id)

        self.assertEqual(result["verification_status"], "publication_verified")
        self.assertTrue(result["execution_request_id"])
        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-333.md").exists())
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True)
        commit_sha = commit.stdout.strip()
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.split()
        self.assertEqual(parents, [commit_sha])
        self.assertIn(f"commit:{commit_sha}", result["mutation_summary"])
        self.assertIn("repository_state_before:unborn", result["mutation_summary"])
        self.assertIn("parent_commit:none", result["mutation_summary"])
        self.assertIn("Git commit created", " ".join(item["phase"] for item in result["timeline"]))
