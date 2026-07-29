from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.managed_secrets.fixtures import encrypted_facade
from src.core.managed_secrets.service import PurposeBoundSecretReader
from src.core.trusted_signing.service import TrustedSignerService


class ManagedSecretSignerIntegrationPhase30Test(unittest.TestCase):
    def test_real_local_ed25519_signer_smoke_rotation_revocation_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facade = encrypted_facade(root / "app.sqlite", root / "vault")
            facade.authz.grant_role("alice", "secret_operator")
            facade.authz.grant_role("bob", "security_approver")
            secret = facade.create_reference(
                secret_type="ed25519_private_key",
                display_name="Managed signer",
                purpose_allowlist=("certification_signing",),
                created_by="alice",
            )["secret"]
            facade.generate_ed25519(secret["id"], actor="alice")
            facade.validate(secret["id"])
            facade.approve(
                secret["id"],
                action_type="activate_production_signer",
                requester_id="alice",
                approver_id="bob",
            )
            facade.activate(secret["id"], action_type="activate_production_signer")
            reader = PurposeBoundSecretReader(facade, purpose="certification_signing", consumer="trusted_signer")
            signer_service = TrustedSignerService(database_path=root / "app.sqlite", secret_reader=reader)
            signer_service.enroll(
                signer_id="signer.managed.one",
                display_name="Managed signer one",
                private_key_secret_reference=secret["id"],
                operator_id="alice",
            )
            signer_service.approve("signer.managed.one", reviewer_id="bob", requester_id="alice")
            signer_service.activate("signer.managed.one")
            payload = {"schema_version": "1.0", "evidence_type": "deterministic_staging_certification"}
            envelope = signer_service.sign_payload(
                "signer.managed.one",
                payload,
                evidence_type="deterministic_staging_certification",
                source_type="local",
            )
            self.assertEqual(signer_service.verify_payload("signer.managed.one", payload, envelope), "valid")
            facade_restarted = encrypted_facade(root / "app.sqlite", root / "vault")
            reader_restarted = PurposeBoundSecretReader(
                facade_restarted, purpose="certification_signing", consumer="trusted_signer"
            )
            restarted = TrustedSignerService(database_path=root / "app.sqlite", secret_reader=reader_restarted)
            self.assertEqual(restarted.verify_payload("signer.managed.one", payload, envelope), "valid")
            replacement = facade_restarted.create_reference(
                secret_type="ed25519_private_key",
                display_name="Managed signer replacement",
                purpose_allowlist=("certification_signing",),
                created_by="alice",
            )["secret"]
            facade_restarted.generate_ed25519(replacement["id"], actor="alice")
            facade_restarted.validate(replacement["id"])
            facade_restarted.authz.grant_role("bob", "security_approver")
            facade_restarted.approve(
                replacement["id"],
                action_type="activate_production_signer",
                requester_id="alice",
                approver_id="bob",
            )
            facade_restarted.activate(replacement["id"], action_type="activate_production_signer")
            rotated = restarted.rotate(
                "signer.managed.one",
                new_signer_id="signer.managed.two",
                new_secret_reference=replacement["id"],
            )
            self.assertEqual(rotated["rotation"]["old_signer_id"], "signer.managed.one")
            self.assertEqual(restarted.verify_payload("signer.managed.one", payload, envelope), "valid")
            restarted.revoke("signer.managed.two", reason="key_compromise")
            self.assertNotIn("PRIVATE KEY", str(facade_restarted.support_bundle_summary()))


if __name__ == "__main__":
    unittest.main()
