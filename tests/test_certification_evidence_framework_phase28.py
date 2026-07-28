import tempfile
import unittest
from pathlib import Path

from integrations.certification_evidence.fixtures import canonical_report_fixture
from src.core.certification_evidence.canonical import canonical_json_bytes
from src.core.certification_evidence.contracts import (
    CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION,
    CERTIFICATION_EVIDENCE_PACKAGE_CONTRACT_VERSION,
)
from src.core.certification_evidence.errors import CertificationEvidenceError
from src.core.certification_evidence.service import CertificationEvidenceService


class CertificationEvidenceFrameworkPhase28Tests(unittest.TestCase):
    def test_contracts_canonicalization_and_package_flow(self) -> None:
        self.assertEqual(CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(CERTIFICATION_EVIDENCE_PACKAGE_CONTRACT_VERSION, "1.0")
        left = canonical_json_bytes({"b": 2, "a": 1})
        right = canonical_json_bytes({"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertEqual(left, b'{"a":1,"b":2}')
        with self.assertRaises(CertificationEvidenceError):
            canonical_json_bytes({"path": "content/drafts/private"})

    def test_evidence_package_export_import_review_and_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            created = service.generate_deterministic_evidence()
            evidence = created["evidence"]
            self.assertEqual(evidence["trust_status"], "unsigned_local")
            self.assertEqual(evidence["signature_status"], "not_configured")
            exported = service.export_evidence(evidence["package_id"])
            self.assertEqual(exported["media_type"], "application/zip")
            imported = service.import_evidence(exported["data"])
            self.assertEqual(imported["evidence"]["package_id"], evidence["package_id"])
            self.assertEqual(service.verify(evidence["package_id"])["technical_valid"], True)
            review = service.review(evidence["package_id"], decision="approved")["review"]
            self.assertEqual(review["evidence_checksum"], evidence["package_checksum"])
            revoked = service.revoke(evidence["package_id"])["revocation"]
            self.assertEqual(revoked["target_type"], "evidence_package")
            self.assertEqual(service.get_evidence(evidence["package_id"])["evidence"]["trust_status"], "revoked")

    def test_report_fixture_can_be_canonicalized(self) -> None:
        canonical = canonical_json_bytes(canonical_report_fixture())
        self.assertIn(b"deterministic_only", canonical)


if __name__ == "__main__":
    unittest.main()
