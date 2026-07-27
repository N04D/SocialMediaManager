from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.operations import StorageBackupService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationBackupPhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.backups = StorageBackupService(self.service.repository, Path(self.tmp.name) / "ops")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_consistent_backup_catalog_and_invalid_destination(self) -> None:
        backup = self.backups.create_backup()
        self.assertEqual(backup.status, "completed")
        self.assertEqual(backup.validation_status, "valid")
        self.assertGreater(backup.backup_size_bytes, 0)
        catalog = self.backups.list_backups()
        self.assertEqual(catalog[0].id, backup.id)
        with self.assertRaises(OwnedPublicationError):
            self.backups.create_backup(destination_reference_id="../not-registered")

    def test_existing_backup_is_preserved_on_unavailable_destination(self) -> None:
        backup = self.backups.create_backup()
        with self.assertRaises(OwnedPublicationError):
            self.backups.destination("arbitrary")
        self.assertEqual(self.backups.get_backup(backup.id).backup_checksum, backup.backup_checksum)


if __name__ == "__main__":
    unittest.main()
