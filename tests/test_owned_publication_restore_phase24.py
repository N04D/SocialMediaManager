from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.operations import StorageBackupService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationRestorePhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.backups = StorageBackupService(self.service.repository, Path(self.tmp.name) / "ops")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_staged_restore_validation_and_checksum_mismatch(self) -> None:
        backup = self.backups.create_backup()
        validation = self.backups.validate_restore(backup.id)
        self.assertEqual(validation.status, "valid")
        self.assertEqual(validation.foreign_key_check, "ok")
        backup_path = self.backups.destination(backup.destination_reference) / f"{backup.id}.sqlite3"
        backup_path.write_bytes(b"not sqlite")
        invalid = self.backups.validate_restore(backup.id)
        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(invalid.integrity_check, "checksum_mismatch")

    def test_restore_never_overwrites_active_database(self) -> None:
        backup = self.backups.create_backup()
        before = self.service.repository.database_path.read_bytes()
        self.backups.validate_restore(backup.id)
        self.assertEqual(self.service.repository.database_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
