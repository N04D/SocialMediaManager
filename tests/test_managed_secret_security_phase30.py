from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from integrations.managed_secrets.fixtures import encrypted_facade
from src.plugin_sdk.cli import secrets_cmd


class ManagedSecretSecurityPhase30Test(unittest.TestCase):
    def test_no_secret_cli_args_supportbundle_or_database_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facade = encrypted_facade(root / "app.sqlite", root / "vault")
            secret = facade.create_reference(
                secret_type="github_read_only_token",
                display_name="No echo token",
                purpose_allowlist=("github_actions_read",),
            )["secret"]
            facade.set_value(secret["id"], b"super-secret-token")
            self.assertNotIn(b"super-secret-token", (root / "app.sqlite").read_bytes())
            self.assertNotIn("super-secret-token", str(facade.support_bundle_summary()))
            args = argparse.Namespace(secrets_command="set", secret_id=secret["id"], stdin=False)
            self.assertEqual(secrets_cmd(args), 0)


if __name__ == "__main__":
    unittest.main()
