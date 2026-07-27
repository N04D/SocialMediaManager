from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository


class CampaignWorkspacePhase23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DatabaseOwnedPublicationRepository(Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_campaign_create_pause_resume_and_reload(self) -> None:
        campaign = self.repo.create_campaign(
            "workspace-1", "Launch Campaign", campaign_id="campaign-1", timezone="Europe/Amsterdam"
        )
        self.assertEqual(campaign.status, "draft")
        paused = self.repo.update_campaign_status(campaign.id, "paused", expected_version=campaign.version)
        self.assertEqual(paused.status, "paused")
        resumed = self.repo.update_campaign_status(campaign.id, "active", expected_version=paused.version)
        self.assertEqual(resumed.status, "active")
        reloaded = DatabaseOwnedPublicationRepository(self.repo.database_path)
        self.assertEqual(reloaded.get_campaign(campaign.id).status, "active")

    def test_campaign_concurrency_conflict(self) -> None:
        campaign = self.repo.create_campaign("workspace-1", "Launch Campaign", campaign_id="campaign-1")
        self.repo.update_campaign_status(campaign.id, "paused", expected_version=campaign.version)
        with self.assertRaises(OwnedPublicationError):
            self.repo.update_campaign_status(campaign.id, "active", expected_version=campaign.version)

    def test_occurrence_materialization_claim_and_recovery(self) -> None:
        occurrence = self.repo.materialize_occurrence(
            "workspace-1", "schedule-1", "target-1", "2026-07-27T09:00:00Z", idempotency_key="occurrence"
        )
        same = self.repo.materialize_occurrence(
            "workspace-1", "schedule-1", "target-1", "2026-07-27T09:00:00Z", idempotency_key="occurrence"
        )
        self.assertEqual(occurrence["id"], same["id"])
        self.assertTrue(self.repo.claim_occurrence(occurrence["id"], "worker-a", "2000-01-01T00:00:00Z"))
        recovery = self.repo.recovery()
        self.assertGreaterEqual(recovery["expired_occurrence_leases_released"], 1)
        self.assertFalse(recovery["blind_retry"])


if __name__ == "__main__":
    unittest.main()
