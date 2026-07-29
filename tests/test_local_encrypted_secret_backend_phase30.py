from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.managed_secrets.errors import ManagedSecretError
from src.providers.secrets.local_encrypted import EphemeralTestKeySource, LocalEncryptedSecretBackend
from src.providers.secrets.local_encrypted.storage import safe_record_name


class LocalEncryptedSecretBackendPhase30Test(unittest.TestCase):
    def test_aes_gcm_unique_nonce_associated_data_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalEncryptedSecretBackend(
                vault_dir=Path(tmp) / "vault", master_key_source=EphemeralTestKeySource()
            )
            first = backend.create(
                reference_id="secretref:first",
                secret_type="generic_api_token",
                scope="host",
                version=1,
                value=b"synthetic-token",
            )
            second = backend.create(
                reference_id="secretref:second",
                secret_type="generic_api_token",
                scope="host",
                version=1,
                value=b"synthetic-token",
            )
            self.assertNotEqual(first["backend_record_reference"], second["backend_record_reference"])
            self.assertEqual(
                backend.read(reference_id="secretref:first", secret_type="generic_api_token", scope="host", version=1),
                b"synthetic-token",
            )
            record = Path(tmp) / "vault" / safe_record_name("secretref:first", 1)
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic-token", record.read_text(encoding="utf-8"))
            payload["ciphertext"] = payload["ciphertext"][:-4] + "AAAA"
            record.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ManagedSecretError) as raised:
                backend.read(reference_id="secretref:first", secret_type="generic_api_token", scope="host", version=1)
            self.assertEqual(raised.exception.code, "vault.gcm_authentication_failed")

    def test_user_owned_vault_path_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ManagedSecretError):
                LocalEncryptedSecretBackend(
                    vault_dir=Path(tmp) / "content" / "vault",
                    master_key_source=EphemeralTestKeySource(),
                )


if __name__ == "__main__":
    unittest.main()
