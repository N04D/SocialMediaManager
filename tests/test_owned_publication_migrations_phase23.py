from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.persistence import (
    MIGRATION_ID,
    DatabaseOwnedPublicationRepository,
    migration_checksum,
)


class OwnedPublicationMigrationsPhase23Tests(unittest.TestCase):
    def test_empty_database_migrates_and_rerun_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            first = DatabaseOwnedPublicationRepository(db)
            second = DatabaseOwnedPublicationRepository(db)
            self.assertEqual(first.health().schema_version, 1)
            self.assertEqual(second.migrations()["migrations"][0]["checksum"], migration_checksum())

    def test_interrupted_migration_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TABLE owned_publication_schema_migrations "
                    "(id TEXT PRIMARY KEY, version INTEGER, checksum TEXT, applied_at TEXT, status TEXT)"
                )
                connection.execute(
                    "INSERT INTO owned_publication_schema_migrations VALUES (?, ?, ?, ?, ?)",
                    (MIGRATION_ID, 1, migration_checksum(), "now", "started"),
                )
            with self.assertRaises(OwnedPublicationError):
                DatabaseOwnedPublicationRepository(db)

    def test_incompatible_checksum_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            repo = DatabaseOwnedPublicationRepository(db)
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute("UPDATE owned_publication_schema_migrations SET checksum='bad'")
            with self.assertRaises(OwnedPublicationError):
                DatabaseOwnedPublicationRepository(db)


if __name__ == "__main__":
    unittest.main()
