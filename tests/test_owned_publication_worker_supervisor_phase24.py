from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.operations import REQUIRED_WORKERS, OwnedPublicationWorkerSupervisor
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationWorkerSupervisorPhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_startup_cycle_health_shutdown_and_restart(self) -> None:
        supervisor = OwnedPublicationWorkerSupervisor(self.service.repository, batch_size=4)
        startup = supervisor.startup()
        self.assertTrue(startup["started"])
        self.assertEqual(
            {worker["worker_type"] for worker in startup["workers"]["workers"]},
            set(REQUIRED_WORKERS),
        )
        cycle = supervisor.run_cycle()
        self.assertEqual(cycle["duplicate_mutations"], 0)
        health = supervisor.health()
        self.assertTrue(health["required_workers_ready"])
        self.assertGreaterEqual(
            sum(worker["processed_items"] for worker in health["workers"]),
            1,
        )
        shutdown = supervisor.graceful_shutdown()
        self.assertTrue(shutdown["shutdown"])
        restarted = OwnedPublicationWorkerSupervisor(self.service.repository)
        self.assertTrue(restarted.startup()["started"])

    def test_storage_gate_blocks_workers_when_storage_health_fails(self) -> None:
        missing_parent_db = Path(self.tmp.name) / "missing" / "owned.sqlite3"
        repo = OwnedPublicationWorkspaceService(database_path=missing_parent_db).repository
        repo.database_path.unlink()
        supervisor = OwnedPublicationWorkerSupervisor(repo)
        startup = supervisor.startup()
        self.assertFalse(startup["started"])
        self.assertEqual(startup["reason"], "storage_not_ready")


if __name__ == "__main__":
    unittest.main()
