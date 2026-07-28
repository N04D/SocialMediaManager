import tempfile
import unittest
from pathlib import Path

from integrations.trusted_signing.fixtures import signer_secret_fixture
from src.core.certification_evidence.models import CertificationSignatureEnvelope
from src.core.trusted_signing.errors import TrustedSigningError
from src.core.trusted_signing.service import TrustedSignerService


class TrustedSignerLifecyclePhase29Tests(unittest.TestCase):
    def test_enroll_approve_activate_sign_rotate_and_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, reference = signer_secret_fixture("secretref:signer/one")
            service = TrustedSignerService(database_path=Path(tmp) / "owned.sqlite3", secret_reader=store)
            service.enroll(signer_id="signer-1", display_name="One", private_key_secret_reference=reference)
            with self.assertRaises(TrustedSigningError):
                service.approve("signer-1", reviewer_id="operator-a", requester_id="operator-a")
            service.approve("signer-1", reviewer_id="operator-b", requester_id="operator-a")
            service.activate("signer-1")
            health = service.health("signer-1")["health"]
            self.assertEqual(health["status"], "healthy")
            payload = {"schema_version": "1.0", "value": "safe"}
            envelope = service.sign_payload(
                "signer-1",
                payload,
                evidence_type="deterministic_staging_certification",
                source_type="local",
            )
            self.assertIsInstance(envelope, CertificationSignatureEnvelope)
            self.assertEqual(service.verify_payload("signer-1", payload, envelope), "valid")
            self.assertEqual(
                service.verify_payload("signer-1", payload | {"value": "changed"}, envelope), "payload_mismatch"
            )

            store.put(
                "secretref:signer/two",
                __import__(
                    "src.core.trusted_signing.algorithms", fromlist=["generate_private_key_pem"]
                ).generate_private_key_pem(),
            )
            service.rotate("signer-1", new_signer_id="signer-2", new_secret_reference="secretref:signer/two")
            service.approve("signer-2", reviewer_id="operator-c", requester_id="operator-b")
            service.activate("signer-2")
            self.assertEqual(service.verify_payload("signer-1", payload, envelope), "valid")
            service.revoke("signer-1", reason="administrative_retirement")
            self.assertEqual(service.verify_payload("signer-1", payload, envelope), "valid")
            service.revoke("signer-2", reason="key_compromise")
            self.assertEqual(service.health("signer-2")["health"]["status"], "invalid")

    def test_key_material_changed_degrades_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, reference = signer_secret_fixture("secretref:signer/drift")
            service = TrustedSignerService(database_path=Path(tmp) / "owned.sqlite3", secret_reader=store)
            service.enroll(signer_id="signer-drift", display_name="Drift", private_key_secret_reference=reference)
            service.approve("signer-drift", reviewer_id="operator-b", requester_id="operator-a")
            service.activate("signer-drift")
            store.put(
                reference,
                __import__(
                    "src.core.trusted_signing.algorithms", fromlist=["generate_private_key_pem"]
                ).generate_private_key_pem(),
            )
            self.assertEqual(service.health("signer-drift")["health"]["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
