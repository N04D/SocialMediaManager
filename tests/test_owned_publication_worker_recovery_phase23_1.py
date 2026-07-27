from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository
from src.core.owned_publication.service import OwnedPublicationWorkspaceService
from src.core.owned_publication.worker import OwnedPublicationOperationsWorker


class OwnedPublicationWorkerRecoveryPhase231Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "owned.sqlite3"
        self.service = OwnedPublicationWorkspaceService(database_path=self.db)
        self.repo: DatabaseOwnedPublicationRepository = self.service.repository

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_crashed_reconciliation_worker_reclaims_after_expiry_without_mutation_retry(self) -> None:
        item_id = "rec-deployment-pending"
        lease = self.repo.claim_reconciliation(item_id, "worker-crashed", "2099-01-01T00:00:00Z")
        self.assertEqual(lease.status, "claimed")
        self.assertTrue(self.repo.heartbeat_reconciliation(item_id, "worker-crashed", "2099-01-01T00:00:30Z"))
        blocked = self.repo.claim_reconciliation(item_id, "worker-b", "2099-01-01T00:01:00Z")
        self.assertEqual(blocked.status, "busy")

        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE reconciliation_items SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00Z", item_id),
            )
            connection.execute(
                "UPDATE reconciliation_leases SET expires_at=? WHERE reconciliation_item_id=?",
                ("2000-01-01T00:00:00Z", item_id),
            )
            connection.commit()

        recovery = self.repo.recovery()
        self.assertEqual(recovery["expired_reconciliation_leases_released"], 1)
        self.assertFalse(recovery["blind_retry"])
        worker_b = OwnedPublicationOperationsWorker(self.repo, worker_id="worker-b", batch_size=4)
        worker_b.run_until_idle()

        item = self.repo.get_reconciliation_item(item_id)
        self.assertEqual(item.manual_action, "read-only certification check")
        with sqlite3.connect(self.db) as connection:
            attempts = connection.execute(
                "SELECT action, status, safe_summary_json FROM reconciliation_attempts WHERE reconciliation_item_id=?",
                (item_id,),
            ).fetchall()
            mutation_retries = connection.execute(
                "SELECT COUNT(id) FROM reconciliation_attempts WHERE safe_summary_json LIKE '%new_mutation%true%'"
            ).fetchone()[0]
        self.assertGreaterEqual(len(attempts), 1)
        self.assertTrue(all(row[0] == "read_only_check" for row in attempts))
        self.assertEqual(mutation_retries, 0)

    def test_occurrence_lease_expiry_allows_reclaim_and_preserves_unique_event(self) -> None:
        result = self.repo.materialize_occurrence(
            "workspace-1",
            "schedule-reclaim",
            "target-linkedin",
            "2026-07-27T12:00:00Z",
            idempotency_key="occurrence-reclaim",
        )
        occurrence_id = str(result["id"])
        self.assertTrue(self.repo.claim_occurrence(occurrence_id, "worker-a", "2099-01-01T00:00:00Z"))
        self.assertFalse(self.repo.claim_occurrence(occurrence_id, "worker-b", "2099-01-01T00:00:30Z"))

        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE publication_occurrences SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00Z", occurrence_id),
            )
            connection.commit()

        recovery = self.repo.recovery()
        self.assertEqual(recovery["expired_occurrence_leases_released"], 1)
        worker_b = OwnedPublicationOperationsWorker(self.repo, worker_id="worker-b", batch_size=4)
        worker_b.run_until_idle()

        timeline = self.repo.list_timeline("attempt-" + occurrence_id)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].mutation_state, "pre_mutation")
        self.assertIn("No mutation", timeline[0].safe_evidence_summary)


if __name__ == "__main__":
    unittest.main()
