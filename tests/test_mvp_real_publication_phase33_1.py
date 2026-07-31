from __future__ import annotations

from tests.phase331_support import Phase331TestCase


class MVPRealPublicationPhase331Tests(Phase331TestCase):
    def test_plan_id_confirmation_execution_commit_and_result_page(self) -> None:
        session_id, repo, result = self.run_real_publication_flow()
        self.assertTrue(result["publication_plan_id"].startswith("plan-"))
        self.assertTrue(result["execution_request_id"].startswith("execution-"))
        commit = result["mutation_summary"][0].removeprefix("commit:")
        self.assertEqual(commit, self.git(repo, "rev-parse", "HEAD"))
        result_page = self.page(f"/setup/{session_id}/result")
        for value in (
            result["content_revision_id"],
            result["publication_plan_id"],
            result["execution_request_id"],
            commit,
            result["public_url"],
        ):
            self.assertIn(value, result_page)
        self.assertIn("push:none", ",".join(result["mutation_summary"]))

    def git(self, repo, *args: str) -> str:
        import subprocess

        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
