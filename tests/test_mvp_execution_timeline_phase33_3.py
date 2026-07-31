from __future__ import annotations

from tests.phase333_support import Phase333TestCase


class MVPExecutionTimelinePhase333Tests(Phase333TestCase):
    def test_timeline_commit_success_requires_commit_sha(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)
            result = self.publish_session(session_id)

        commit_events = [item for item in result["timeline"] if item["phase"] == "Git commit created"]
        self.assertEqual(len(commit_events), 1)
        self.assertEqual(commit_events[0]["status"], "completed")
        self.assertTrue(commit_events[0]["safe_evidence_summary"])
        self.assertTrue(any(part.startswith("commit:") for part in result["mutation_summary"]))
