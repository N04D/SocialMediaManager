from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.operations import SupportBundleService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationSupportBundlePhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_support_bundle_manifest_checksums_and_redaction(self) -> None:
        bundle = SupportBundleService(self.service.repository, Path(self.tmp.name) / "bundles").create_bundle(
            self.service.release_check_payload(require_certification=False)
        )
        path = Path(self.tmp.name) / "bundles" / bundle["path_reference"]
        self.assertTrue(path.exists())
        self.assertGreater(len(bundle["checksums"]), 3)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            combined = "\n".join(archive.read(name).decode("utf-8") for name in names)
        self.assertIn("manifest.json", names)
        self.assertNotIn("private key", combined.lower())
        self.assertNotIn("authorization", combined.lower())
        self.assertNotIn("markdown_body", combined)
        self.assertNotIn("owned.sqlite3", names)

    def test_support_bundle_rejects_size_limit_without_partial_success(self) -> None:
        service = SupportBundleService(self.service.repository, Path(self.tmp.name) / "bundles-small")
        with self.assertRaises(OwnedPublicationError):
            service.create_bundle(self.service.release_check_payload(require_certification=False), max_bytes=1)
        self.assertEqual(list((Path(self.tmp.name) / "bundles-small").glob("*.zip")), [])


if __name__ == "__main__":
    unittest.main()
