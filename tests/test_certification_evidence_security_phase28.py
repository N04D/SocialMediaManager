import unittest
from pathlib import Path


class CertificationEvidenceSecurityPhase28Tests(unittest.TestCase):
    def test_boundary_terms_are_negative_or_safe(self) -> None:
        paths = [
            Path("src/core/certification_evidence"),
            Path("integrations/certification_evidence"),
        ]
        text = "\n".join(file.read_text(encoding="utf-8") for root in paths for file in root.glob("*.py"))
        self.assertNotIn("extractall", text)
        self.assertNotIn("trusted=true", text)
        self.assertNotIn("live_certified", text)
        self.assertIn("signature_status", text)

    def test_support_bundle_redacts_raw_package_and_user_content(self) -> None:
        from tempfile import TemporaryDirectory

        from src.core.certification_evidence.service import CertificationEvidenceService

        with TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
            bundle = service.support_bundle()
            lowered = str(bundle).lower()
            self.assertNotIn("raw package", lowered)
            self.assertNotIn("content/drafts", lowered)
            self.assertFalse(bundle["certification"]["contains_private_key"])
            self.assertFalse(bundle["certification"]["contains_raw_package"])


if __name__ == "__main__":
    unittest.main()
