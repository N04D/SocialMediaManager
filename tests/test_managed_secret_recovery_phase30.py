from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.managed_secrets.fixtures import encrypted_facade
from src.providers.secrets.local_encrypted.recovery import scan_orphans


class ManagedSecretRecoveryPhase30Test(unittest.TestCase):
    def test_crash_recovery_temp_orphan_and_rotation_pending_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            facade = encrypted_facade(root / "app.sqlite", vault)
            secret = facade.create_reference(
                secret_type="generic_api_token",
                display_name="Recoverable secret",
                purpose_allowlist=("github_actions_read",),
            )["secret"]
            facade.set_value(secret["id"], b"version-one")
            (vault / ".partial.secret.json.tmp").write_text("partial", encoding="utf-8")
            scan = scan_orphans(vault)
            self.assertEqual(scan["orphan_temporary_records"], [".partial.secret.json.tmp"])
            restarted = encrypted_facade(root / "app.sqlite", vault)
            self.assertEqual(restarted.vault_health()["ready"], True)
            current = restarted.repository.get_reference(secret["id"])
            self.assertIn(current["status"], {"pending_validation", "pending_value"})
            self.assertFalse(scan["automatic_plaintext_recovery"])


if __name__ == "__main__":
    unittest.main()
