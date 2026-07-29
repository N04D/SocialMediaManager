from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.managed_secrets.fixtures import encrypted_facade
from src.core.managed_secrets.contracts import (
    LOCAL_ENCRYPTED_SECRET_BACKEND_VERSION,
    MANAGED_SECRET_FRAMEWORK_VERSION,
    OPERATOR_APPROVAL_CONTRACT_VERSION,
    SECRET_BACKEND_CONTRACT_VERSION,
    SECRET_LEASE_CONTRACT_VERSION,
    SECRET_REFERENCE_CONTRACT_VERSION,
)


class ManagedSecretsFrameworkPhase30Test(unittest.TestCase):
    def test_contracts_reference_lifecycle_and_metadata_only_outputs(self) -> None:
        self.assertEqual(MANAGED_SECRET_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(SECRET_REFERENCE_CONTRACT_VERSION, "1.0")
        self.assertEqual(SECRET_BACKEND_CONTRACT_VERSION, "1.0")
        self.assertEqual(SECRET_LEASE_CONTRACT_VERSION, "1.0")
        self.assertEqual(OPERATOR_APPROVAL_CONTRACT_VERSION, "1.0")
        self.assertEqual(LOCAL_ENCRYPTED_SECRET_BACKEND_VERSION, "0.1.0")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facade = encrypted_facade(root / "app.sqlite", root / "vault")
            created = facade.create_reference(
                secret_type="generic_api_token",
                display_name="GitHub token reference",
                purpose_allowlist=("github_actions_read",),
            )["secret"]
            self.assertTrue(created["id"].startswith("secretref:"))
            self.assertTrue(created["value_redacted"])
            self.assertNotIn("plaintext", created)
            self.assertNotIn("ciphertext", created)
            status = facade.status()
            self.assertEqual(status["managed_secrets_status"], "configured")
            self.assertTrue(status["vault_health"]["ready"])


if __name__ == "__main__":
    unittest.main()
