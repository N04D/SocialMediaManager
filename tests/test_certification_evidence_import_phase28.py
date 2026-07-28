import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from integrations.certification_evidence.corruption_fixtures import tamper_first_report_byte, traversal_archive
from src.core.certification_evidence.errors import CertificationEvidenceError
from src.core.certification_evidence.service import CertificationEvidenceService


class CertificationEvidenceImportPhase28Tests(unittest.TestCase):
    def test_valid_import_idempotent_and_same_id_different_checksum_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "cert.sqlite"
            source = CertificationEvidenceService(database_path=database)
            created = source.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
            data = source.export_evidence(created["evidence"]["package_id"])["data"]
            imported = source.import_evidence(data)
            again = source.import_evidence(data)
            self.assertEqual(imported["evidence"]["package_id"], again["evidence"]["package_id"])
            with self.assertRaises(CertificationEvidenceError):
                source.import_evidence(tamper_first_report_byte(data))

    def test_archive_traversal_absolute_duplicate_and_forbidden_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            with self.assertRaises(CertificationEvidenceError):
                service.import_evidence(traversal_archive())
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("/absolute.json", b"{}")
                archive.writestr("manifest.json", b"{}")
            with self.assertRaises(CertificationEvidenceError):
                service.import_evidence(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
