import tempfile
import unittest
from pathlib import Path

from integrations.trusted_signing.fixtures import signer_secret_fixture
from src.core.trusted_signing.contracts import (
    HOST_SIGNER_CONTRACT_VERSION,
    SIGNER_ENROLLMENT_CONTRACT_VERSION,
    SIGNER_ROTATION_CONTRACT_VERSION,
    TRUSTED_SIGNER_FRAMEWORK_VERSION,
)
from src.core.trusted_signing.service import TrustedSignerService


class TrustedSignerFrameworkPhase29Tests(unittest.TestCase):
    def test_contracts_algorithm_and_secret_reference_boundary(self) -> None:
        self.assertEqual(TRUSTED_SIGNER_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(HOST_SIGNER_CONTRACT_VERSION, "1.0")
        self.assertEqual(SIGNER_ENROLLMENT_CONTRACT_VERSION, "1.0")
        self.assertEqual(SIGNER_ROTATION_CONTRACT_VERSION, "1.0")
        with tempfile.TemporaryDirectory() as tmp:
            store, reference = signer_secret_fixture()
            service = TrustedSignerService(database_path=Path(tmp) / "owned.sqlite3", secret_reader=store)
            enrolled = service.enroll(
                signer_id="host-signer-1",
                display_name="Host signer",
                private_key_secret_reference=reference,
            )
            signer = enrolled["signer"]
            self.assertEqual(signer["algorithm_identifier"], "Ed25519")
            self.assertEqual(signer["status"], "pending_approval")
            self.assertEqual(signer["secret_reference_status"], "present")
            self.assertNotIn("PRIVATE KEY", str(signer))
            self.assertNotIn("private_key_secret_reference", signer)


if __name__ == "__main__":
    unittest.main()
