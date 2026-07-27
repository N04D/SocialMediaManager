from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard import render_owned_publication_workspace_page
from src.core.owned_publication import OwnedPublicationWorkspaceService


class OwnedPublicationComposerPhase22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "composer.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_website_editor_preview_uses_publication_renderer(self) -> None:
        preview = self.service.preview("content-owned-1", "website")
        self.assertTrue(preview["sanitized"])
        self.assertIn('content_revision_id: "revision-owned-1"', preview["frontmatter"])
        self.assertEqual(preview["markdown"]["relative_path"], "articles/owned-funnel-launch.md")
        self.assertEqual(preview["markdown"]["public_url"], "https://example.test/articles/owned-funnel-launch")

    def test_social_variant_editors_are_editable_without_silent_overwrite(self) -> None:
        saved = self.service.put_variant(
            "content-owned-1",
            "linkedin",
            {"expected_revision": "revision-owned-1", "text": "Manual LinkedIn edit"},
        )
        self.assertEqual(saved["status"], "variant_saved")
        self.assertFalse(saved["silent_overwrite"])
        mastodon = self.service.preview("content-owned-1", "mastodon")
        self.assertTrue(mastodon["attribution_bound"])

    def test_markdown_preview_sanitizes_script_and_unsafe_url_text(self) -> None:
        preview = self.service.preview("content-owned-1", "website")
        html = preview["html"]
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("javascript:", html.lower())
        self.assertIn("&lt;!-- smm-content-revision", html)

    def test_dashboard_workspace_contains_accessible_core_regions(self) -> None:
        markup = render_owned_publication_workspace_page()
        self.assertIn('aria-labelledby="owned-workspace-title"', markup)
        self.assertIn('role="tablist"', markup)
        self.assertIn("<label>Title", markup)
        self.assertIn("Dependency graph", markup)
        self.assertIn("Execution timeline", markup)
        self.assertIn("Funnel dashboard", markup)
        self.assertNotIn("private key", markup.lower())


if __name__ == "__main__":
    unittest.main()
