from __future__ import annotations

from pathlib import Path

from tests.phase331_support import Phase331TestCase


class MVPRealDestinationPhase331Tests(Phase331TestCase):
    def test_real_destination_registration_and_doctor_use_selected_repository(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            html = self.page(f"/setup/{session_id}/website_account")
        self.assertIn("Dogfood Site", html)
        for label in ("Repository registered", "Git repository", "Branch", "Write permissions", "Push policy"):
            self.assertIn(label, html)
        self.assertIn("PASS", html)
        self.assertIn("WARN", html)
        self.assertIn(repo.name, html)

    def test_product_repository_and_protected_paths_are_blocked(self) -> None:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        product = Path(__file__).resolve().parents[1]
        _payload, status = self.post(
            f"/setup/{session_id}/complete",
            {
                "step_id": "publication_destination",
                "display_name": "Product repo",
                "managed_root": str(product.parent),
                "repository": product.name,
                "branch": "main",
                "public_url_template": "http://127.0.0.1:1/articles/{slug}.md",
            },
        )
        self.assertEqual(status, 400)
