from __future__ import annotations

import subprocess

from tests.phase334_support import Phase334TestCase


class MVPClosedAlphaReadinessPhase334Tests(Phase334TestCase):
    def test_closed_alpha_publication_details_without_push_or_production_claim(self) -> None:
        session_id, repo, publication = self.publish_custom_seo()
        page = self.page(f"/setup/{session_id}/result")
        remotes = subprocess.run(["git", "remote", "-v"], cwd=repo, text=True, capture_output=True, check=True)

        self.assertIn("Publishing status", page)
        self.assertIn("Completed", page)
        self.assertIn("push:none", publication["mutation_summary"])
        self.assertEqual(remotes.stdout.strip(), "")
        self.assertNotIn("production_ready=true", page)
        operations = self.page("/operations")
        self.assertIn("External plugin sandbox ready", operations)
        self.assertIn("CI certification ready", operations)
