from __future__ import annotations

import unittest

from src.core.owned_publication import OWNED_PUBLICATION_WORKSPACE_VERSION, OwnedPublicationWorkspaceService
from src.core.owned_publication.errors import OwnedPublicationError


class OwnedPublicationWorkspacePhase22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OwnedPublicationWorkspaceService()

    def test_workspace_loads_with_routes_navigation_and_safe_sections(self) -> None:
        workspace = self.service.workspace_payload("content-owned-1")
        self.assertEqual(OWNED_PUBLICATION_WORKSPACE_VERSION, "0.1.0")
        self.assertEqual(workspace["content_item_id"], "content-owned-1")
        self.assertIn("website", workspace["variants"])
        self.assertIn("linkedin", workspace["variants"])
        self.assertIn("mastodon", workspace["variants"])
        self.assertEqual(workspace["readiness"]["overall"], "ready")
        self.assertEqual(workspace["publication_plan"]["campaign"], "campaign-owned")
        self.assertFalse(workspace["funnel"]["causality_claimed"])

    def test_new_article_autosave_conflict_and_immutable_revision(self) -> None:
        created = self.service.create_content(
            {
                "id": "content-new",
                "workspace_id": "workspace-1",
                "title": "New article",
                "markdown_body": "# Draft",
            }
        )
        self.assertEqual(created["title"], "New article")
        saved = self.service.autosave("content-new", {"expected_version": 1, "markdown_body": "# Updated"})
        self.assertEqual(saved["status"], "saved")
        self.assertTrue(saved["autosave"]["debounced"])
        self.assertFalse(saved["autosave"]["body_logged"])
        with self.assertRaises(OwnedPublicationError):
            self.service.autosave("content-new", {"expected_version": 1, "markdown_body": "# Lost"})
        revision = self.service.create_revision("content-new", {"expected_version": 2})
        self.assertTrue(revision["immutable"])
        self.assertEqual(revision["revision"]["source_draft_version"], 2)

    def test_workspace_separates_draft_revision_variant_and_snapshot(self) -> None:
        workspace = self.service.workspace_payload()
        self.assertNotEqual(workspace["draft"]["checksum"], "")
        self.assertEqual(workspace["active_revision"]["checksum"], workspace["draft"]["checksum"])
        self.assertEqual(workspace["variants"]["website"]["content_revision_id"], workspace["active_revision"]["id"])
        self.assertRegex(workspace["publication_plan"]["targets"][0]["snapshot_checksum"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            workspace["publication_plan"]["targets"][0]["snapshot_checksum"],
            workspace["evidence"][0]["snapshot_checksum"],
        )

    def test_validation_and_readiness_block_bad_article(self) -> None:
        service = OwnedPublicationWorkspaceService()
        created = service.create_content(
            {"id": "content-empty", "workspace_id": "workspace-1", "title": "", "markdown_body": ""}
        )
        self.assertEqual(created["status"], "draft")
        validation = service.validate_content("content-empty")
        self.assertTrue(validation["blocking"])


if __name__ == "__main__":
    unittest.main()
