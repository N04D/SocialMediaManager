import tempfile
import unittest
from pathlib import Path

from src.core.certification_evidence.service import CertificationEvidenceService


class CertificationEvidenceTrustPhase28Tests(unittest.TestCase):
    def test_unsigned_local_signed_local_ci_and_remote_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            unsigned = service.generate_deterministic_evidence()["evidence"]
            signed = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")[
                "evidence"
            ]
            self.assertEqual(unsigned["trust_status"], "unsigned_local")
            self.assertEqual(signed["trust_status"], "signed_local")
            self.assertEqual(service.remote_ci_status()["artifact_status"], "artifact_not_imported")
            self.assertEqual(service.remote_ci_status()["ci_passed_claim"], "not_claimed")

    def test_required_skip_and_wrong_commit_are_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            bad_commit = "0" * 40
            created = service.create_from_staging_run(
                service.staging.create_run("staging-cert-profile-1")["run"]["id"],
                signer_reference_id="signer.local.deterministic-test",
                source_type="ci",
                commit_sha=bad_commit,
            )
            self.assertEqual(created["evidence"]["trust_status"], "untrusted")


if __name__ == "__main__":
    unittest.main()
