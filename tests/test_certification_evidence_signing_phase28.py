import tempfile
import unittest
from pathlib import Path

from src.core.certification_evidence.models import CertificationRevocation
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.certification_evidence.signatures import verify_signature


class CertificationEvidenceSigningPhase28Tests(unittest.TestCase):
    def test_configured_test_signer_valid_signature_and_no_private_key_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            created = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
            evidence = created["evidence"]
            self.assertEqual(evidence["signature_status"], "valid")
            self.assertEqual(evidence["trust_status"], "signed_local")
            self.assertNotIn("private_key", str(evidence).lower())
            self.assertNotIn("fake-signer:", str(evidence))

    def test_changed_artifact_invalidates_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            created = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
            evidence = service._stored_full(created["evidence"]["package_id"])
            package = service._package_from_dict(evidence)
            payload = {
                "evidence_type": package.evidence_type,
                "workspace_id": package.workspace_id,
                "report": evidence["report"] | {"certification_passed": False},
                "provenance": evidence["provenance"],
                "artifact_manifest": [item.__dict__ for item in package.artifact_manifest],
            }
            self.assertEqual(verify_signature(payload, package.signature_envelope), "payload_mismatch")

    def test_revocation_degrades_trust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            created = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
            evidence_id = created["evidence"]["package_id"]
            service.repository.save_revocation(
                CertificationRevocation(
                    id="rev-1",
                    workspace_id="workspace-1",
                    target_type="evidence_package",
                    target_id=evidence_id,
                    reason="test",
                    revoked_at="2026-07-28T00:00:00Z",
                    revoked_by="operator",
                )
            )
            self.assertEqual(service.get_evidence(evidence_id)["evidence"]["trust_status"], "revoked")


if __name__ == "__main__":
    unittest.main()
