from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.operations import RetentionPolicy, StorageBackupService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationRetentionPhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.backups = StorageBackupService(self.service.repository, Path(self.tmp.name) / "ops")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retention_policy_dry_run_and_last_verified_backup_preserved(self) -> None:
        policy = RetentionPolicy(
            "retention-1",
            "global",
            "old_non_current_derived_readmodels",
            True,
            "P7D",
            10,
            True,
            "preserve",
            "now",
            "now",
        )
        self.assertTrue(policy.dry_run)
        first = self.backups.create_backup()
        second = self.backups.create_backup()
        preview = self.backups.apply_retention(keep_last=1, maximum_total_bytes=1, dry_run=True)
        self.assertTrue(preview["last_verified_backup_preserved"])
        self.assertIn(first.id, preview["delete_candidates"])
        self.assertEqual(self.backups.get_backup(second.id).validation_status, "valid")

    def test_retention_does_not_remove_immutable_evidence_or_unresolved_reconciliation(self) -> None:
        self.assertGreaterEqual(len(self.service.repository.list_reconciliation()), 1)
        preview = self.service.retention_preview({"dry_run": True, "maximum_total_bytes": 1})
        self.assertTrue(preview["dry_run"])
        self.assertGreaterEqual(len(self.service.repository.list_reconciliation()), 1)


if __name__ == "__main__":
    unittest.main()
