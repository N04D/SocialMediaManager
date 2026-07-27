from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.fixtures import build_complete_workspace_fixture
from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository


class ReconciliationQueuePhase23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DatabaseOwnedPublicationRepository(Path(self.tmp.name) / "owned.sqlite3")
        self.item = build_complete_workspace_fixture().reconciliation_queue[0]
        self.repo.detect_reconciliation(self.item, plan_id="plan", attempt_id="attempt", idempotency_key="rec")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reconciliation_item_is_durable_claimable_and_reclaimable(self) -> None:
        lease = self.repo.claim_reconciliation(self.item.id, "worker-a", "2099-01-01T00:00:00Z")
        self.assertEqual(lease.status, "claimed")
        busy = self.repo.claim_reconciliation(self.item.id, "worker-b", "2099-01-01T00:00:00Z")
        self.assertEqual(busy.status, "busy")
        self.assertTrue(self.repo.heartbeat_reconciliation(self.item.id, "worker-a", "2099-01-01T00:05:00Z"))
        self.assertFalse(self.repo.release_reconciliation(self.item.id, "worker-b"))
        self.assertTrue(self.repo.release_reconciliation(self.item.id, "worker-a"))
        reclaimed = self.repo.claim_reconciliation(self.item.id, "worker-b", "2099-01-01T00:10:00Z")
        self.assertEqual(reclaimed.status, "claimed")

    def test_resolution_requires_owner_version_and_never_retries_mutation(self) -> None:
        self.repo.claim_reconciliation(self.item.id, "worker-a", "2099-01-01T00:00:00Z")
        with self.assertRaises(OwnedPublicationError):
            self.repo.resolve_reconciliation(self.item.id, "worker-a", expected_version=99, resolution="checked")
        result = self.repo.resolve_reconciliation(
            self.item.id, "worker-a", expected_version=2, resolution="remote commit verified"
        )
        self.assertFalse(result["new_mutation"])
        with self.assertRaises(OwnedPublicationError):
            self.repo.resolve_reconciliation(
                self.item.id, "worker-a", expected_version=3, resolution="push again", read_only=False
            )

    def test_expired_lease_recovery_releases_work(self) -> None:
        self.repo.claim_reconciliation(self.item.id, "worker-a", "2000-01-01T00:00:00Z")
        recovery = self.repo.recovery()
        self.assertGreaterEqual(recovery["expired_reconciliation_leases_released"], 1)
        self.assertFalse(recovery["blind_retry"])


if __name__ == "__main__":
    unittest.main()
