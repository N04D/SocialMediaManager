from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from src.core.owned_publication.models import ReconciliationItem, stable_checksum, utc_now_iso
from src.core.owned_publication.service import OwnedPublicationWorkspaceService
from src.core.owned_publication.worker import OwnedPublicationOperationsWorker, run_worker_thread


class OwnedPublicationWorkerConcurrencyPhase231Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "owned.sqlite3"
        self.service = OwnedPublicationWorkspaceService(database_path=self.db)
        self.repo = self.service.repository

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_two_workers_claim_each_item_once_against_same_sqlite_database(self) -> None:
        for index in range(3):
            self.repo.materialize_occurrence(
                "workspace-1",
                f"schedule-extra-{index}",
                "target-linkedin",
                f"2026-07-27T10:0{index}:00Z",
                idempotency_key=f"extra-occurrence-{index}",
            )
            self.repo.detect_reconciliation(
                ReconciliationItem(
                    f"rec-worker-{index}",
                    "workspace-1",
                    "publication-worker",
                    "target-website",
                    "channel.markdown_website",
                    "deployment_pending",
                    "remote_acknowledged",
                    "warning",
                    utc_now_iso(),
                    {"public_url": "https://example.test/articles/pending"},
                    "verify_public_url",
                ),
                plan_id="plan-owned-1",
                attempt_id=f"attempt-worker-{index}",
                idempotency_key=f"rec-worker-{index}",
            )

        worker_a = OwnedPublicationOperationsWorker(self.repo, worker_id="worker-a", batch_size=8)
        worker_b = OwnedPublicationOperationsWorker(self.repo, worker_id="worker-b", batch_size=8)
        threads = [run_worker_thread(worker_a), run_worker_thread(worker_b)]
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())

        self.assertEqual(worker_a.execution_model, "thread")
        self.assertGreater(worker_a.stats.processed + worker_b.stats.processed, 0)
        self.assertTrue(worker_a.stats.reconciliation_claims or worker_b.stats.reconciliation_claims)
        self.assertTrue(worker_a.stats.occurrence_claims or worker_b.stats.occurrence_claims)

        with sqlite3.connect(self.db) as connection:
            duplicate_events = connection.execute(
                "SELECT publication_attempt_id, idempotency_key, COUNT(id) "
                "FROM publication_execution_events GROUP BY publication_attempt_id, idempotency_key HAVING COUNT(id) > 1"
            ).fetchall()
            duplicate_evidence = connection.execute(
                "SELECT idempotency_key, COUNT(id) FROM publication_evidence GROUP BY idempotency_key HAVING COUNT(id) > 1"
            ).fetchall()
            active_reconciliation_leases = connection.execute(
                "SELECT reconciliation_item_id, COUNT(id) FROM reconciliation_leases "
                "GROUP BY reconciliation_item_id HAVING COUNT(id) > 1"
            ).fetchall()
            mutation_retries = connection.execute(
                "SELECT COUNT(id) FROM reconciliation_attempts WHERE safe_summary_json LIKE '%new_mutation%true%'"
            ).fetchone()[0]
        self.assertEqual(duplicate_events, [])
        self.assertEqual(duplicate_evidence, [])
        self.assertEqual(active_reconciliation_leases, [])
        self.assertEqual(mutation_retries, 0)

    def test_concurrent_occurrence_materialization_keeps_unique_occurrence(self) -> None:
        results: list[dict[str, object] | BaseException] = []

        def materialize() -> None:
            try:
                results.append(
                    self.repo.materialize_occurrence(
                        "workspace-1",
                        "schedule-concurrent",
                        "target-linkedin",
                        "2026-07-27T11:00:00Z",
                        idempotency_key="same-occurrence",
                    )
                )
            except BaseException as exc:  # pragma: no cover - assertion captures the thread result
                results.append(exc)

        threads = [threading.Thread(target=materialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(item, dict) for item in results))
        expected_id = "occ-" + stable_checksum("same-occurrence")[:12]
        self.assertEqual({str(item["id"]) for item in results if isinstance(item, dict)}, {expected_id})
        with sqlite3.connect(self.db) as connection:
            occurrence_count = connection.execute(
                "SELECT COUNT(id) FROM publication_occurrences WHERE idempotency_key=?", ("same-occurrence",)
            ).fetchone()[0]
        self.assertEqual(occurrence_count, 1)


if __name__ == "__main__":
    unittest.main()
