from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.operations import CertificationGate, ProductionReadinessService, StorageBackupService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationDisasterRecoveryPhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.active_db = Path(self.tmp.name) / "active.sqlite3"
        self.service = OwnedPublicationWorkspaceService(database_path=self.active_db)
        self.backups = StorageBackupService(self.service.repository, Path(self.tmp.name) / "ops")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_backup_restore_recovery_and_no_future_records_or_mutation_replay(self) -> None:
        self.service.create_content(
            {
                "id": "dr-content",
                "workspace_id": "workspace-1",
                "title": "DR article",
                "markdown_body": "# DR",
            }
        )
        backup = self.backups.create_backup()
        self.service.create_content(
            {
                "id": "post-backup-content",
                "workspace_id": "workspace-1",
                "title": "Future",
                "markdown_body": "# Future",
            }
        )
        validation = self.backups.validate_restore(backup.id)
        self.assertEqual(validation.status, "valid")

        restored_path = Path(self.tmp.name) / "restored.sqlite3"
        backup_path = self.backups.destination(backup.destination_reference) / f"{backup.id}.sqlite3"
        with sqlite3.connect(backup_path) as source, sqlite3.connect(restored_path) as target:
            source.backup(target)
        restored = OwnedPublicationWorkspaceService(database_path=restored_path)
        self.assertEqual(restored.get_content("dr-content")["title"], "DR article")
        with self.assertRaises(OwnedPublicationError) as ctx:
            restored.get_content("post-backup-content")
        self.assertEqual(ctx.exception.code, "workspace.not_found")
        recovery = restored.recovery()
        self.assertFalse(recovery["blind_retry"])
        gate = CertificationGate(commit_sha="test")
        browser = gate.evidence_from_result(certification_type="browser_certification", browser_version="chromium")
        worker = gate.evidence_from_result(certification_type="worker_certification")
        restored_backups = StorageBackupService(restored.repository, Path(self.tmp.name) / "restored-ops")
        restored_backups.create_backup()
        report = ProductionReadinessService(restored.repository, backup_service=restored_backups).report(
            browser_evidence=browser,
            worker_evidence=worker,
        )
        self.assertTrue(report.owned_publication_operations_ready)
        self.assertFalse(report.external_plugin_sandbox_ready)


if __name__ == "__main__":
    unittest.main()
