import tempfile
import unittest
from pathlib import Path

from src.core.certification_evidence.errors import CertificationEvidenceError
from src.core.certification_evidence.mcp import CertificationEvidenceMCP
from src.core.certification_evidence.service import CertificationEvidenceService


class CertificationEvidenceOperatorPhase28Tests(unittest.TestCase):
    def test_operator_dry_run_start_compare_review_mcp_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            service.staging.create_profile()
            dry_run = service.dry_run_staging_profile("staging-cert-profile-1")
            self.assertFalse(dry_run["browser_opened"])
            self.assertFalse(dry_run["event_sent"])
            with self.assertRaises(CertificationEvidenceError):
                service.execute_staging_profile("staging-cert-profile-1")
            left = service.generate_deterministic_evidence()["evidence"]
            right = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")[
                "evidence"
            ]
            comparison = service.compare(left["package_id"], right["package_id"])["comparison"]
            self.assertTrue(comparison["shared_commit"])
            service.review(right["package_id"], decision="needs_follow_up", safe_comment="safe follow up")
            readiness = service.readiness()
            self.assertTrue(readiness["certification_evidence_valid"])
            mcp = CertificationEvidenceMCP(service)
            self.assertIn("evidence", mcp.get_certification_evidence())
            self.assertIn("comparison", mcp.compare_certification_evidence(left["package_id"], right["package_id"]))


if __name__ == "__main__":
    unittest.main()
