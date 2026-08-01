from __future__ import annotations

import mvp_dashboard
from tests.phase331_support import Phase331TestCase


class MVPDogfoodStabilizationPhase331Tests(Phase331TestCase):
    def test_real_mode_uses_real_composer_and_no_demo_banner(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            publication = self.create_draft_and_plan(session_id)
        html = self.page(f"/setup/{session_id}")
        self.assertNotIn("Demo environment", html)
        composer = self.page(f"/content/{publication['content_item_id']}/compose?setup_session={session_id}")
        self.assertIn("Article composer", composer)
        self.assertIn("Back to content", composer)
        self.assertIn("Publish", composer)
        self.assertNotIn("Continue to publication plan", composer)
        self.assertNotIn("phase33-fixture", composer)

    def test_fixture_bindings_blocked_in_real_mode(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        _payload, status = self.post(
            f"/setup/{session_id}/complete",
            {
                "step_id": "publication_destination",
                "display_name": "fixture-repository",
                "managed_root": str(self.root),
                "repository": "fixture-repository",
                "branch": "main",
                "public_url_template": "http://127.0.0.1:1/articles/{slug}.md",
            },
        )
        self.assertEqual(status, 400)

    def test_real_markdown_publication_flow_creates_commit_and_verification(self) -> None:
        _session_id, repo, result = self.run_real_publication_flow()
        self.assertEqual(result["verification_status"], "publication_verified")
        self.assertTrue(result["execution_request_id"].startswith("execution-"))
        self.assertIn("commit:", ",".join(result["mutation_summary"]))
        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-001.md").exists())
        self.assertNotIn("push", mvp_dashboard._git(repo, "log", "-1", "--pretty=%B").lower().splitlines()[0])
