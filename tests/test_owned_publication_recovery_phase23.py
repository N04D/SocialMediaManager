from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.fixtures import build_complete_workspace_fixture
from src.core.owned_publication.mcp import OwnedPublicationMCP
from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationRecoveryPhase23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DatabaseOwnedPublicationRepository(Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_timeline_evidence_readmodel_and_integrity_are_durable(self) -> None:
        workspace = build_complete_workspace_fixture()
        event = workspace.timeline[0]
        appended = self.repo.append_execution_event(
            workspace.workspace_id, "attempt-1", "target-website", event, idempotency_key="event-1"
        )
        duplicate = self.repo.append_execution_event(
            workspace.workspace_id, "attempt-1", "target-website", event, idempotency_key="event-1"
        )
        self.assertEqual(appended, duplicate)
        evidence = self.repo.add_evidence(
            workspace.workspace_id, "public_url_evidence", workspace.evidence[0], idempotency_key="evidence-1"
        )
        self.assertEqual(evidence.publication_id, "publication-website-1")
        self.repo.ingest_observation(
            workspace.workspace_id,
            "website.page_views",
            10,
            workspace.content_item_id,
            workspace.active_revision.id,
            "target-website",
            campaign_id="campaign-owned",
            idempotency_key="obs-1",
        )
        readmodel = self.repo.rebuild_readmodel(
            workspace.workspace_id, "ContentFunnelReadModel", workspace.content_item_id
        )
        self.assertTrue(readmodel["current"])
        self.assertEqual(self.repo.readmodels_status()["readmodels"][0]["current"], 1)
        self.assertEqual(self.repo.integrity_scan()["read_only"], True)
        self.assertFalse(self.repo.recovery()["blind_retry"])

    def test_mcp_uses_database_backed_service_after_restart(self) -> None:
        service = OwnedPublicationWorkspaceService(database_path=self.repo.database_path)
        campaign = service.create_campaign({"id": "campaign-mcp", "name": "MCP Campaign"})["campaign"]
        restarted = OwnedPublicationWorkspaceService(database_path=self.repo.database_path)
        mcp = OwnedPublicationMCP(restarted)
        workspace = mcp.get_owned_publication_workspace("content-owned-1")
        campaign_payload = mcp.get_campaign_performance(campaign["id"])
        self.assertTrue(workspace["read_only"])
        self.assertEqual(campaign_payload["campaign"]["id"], "campaign-mcp")
        self.assertFalse(campaign_payload["phase20_2"]["production_ready"])


if __name__ == "__main__":
    unittest.main()
