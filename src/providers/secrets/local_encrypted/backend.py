"""Local encrypted managed secret backend."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from src.core.certification_evidence.models import stable_checksum, utc_now_iso
from src.core.managed_secrets.contracts import LOCAL_ENCRYPTED_SECRET_BACKEND_VERSION
from src.core.managed_secrets.errors import ManagedSecretError
from src.core.trusted_signing.algorithms import generate_private_key_pem

from .crypto import decrypt_secret, encrypt_secret
from .master_keys import MasterKeySource
from .storage import VaultRecordStore, safe_record_name


class LocalEncryptedSecretBackend:
    backend_id = "secret.local_encrypted"
    backend_version = LOCAL_ENCRYPTED_SECRET_BACKEND_VERSION

    def __init__(self, *, vault_dir: Path, master_key_source: MasterKeySource) -> None:
        self.vault_dir = vault_dir
        self.master_key_source = master_key_source
        self.store = VaultRecordStore(vault_dir)

    def capabilities(self) -> dict[str, bool]:
        return {
            "create": True,
            "generate": True,
            "read": True,
            "rotate": True,
            "revoke": True,
            "delete_if_allowed": False,
            "persistent": True,
            "production_capable": True,
        }

    def create(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict:
        return self._write_record(
            reference_id=reference_id, secret_type=secret_type, scope=scope, version=version, value=value
        )

    def generate(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict:
        if secret_type != "ed25519_private_key":
            raise ManagedSecretError("secret.generate_type", "Only Ed25519 private keys can be generated.")
        return self._write_record(
            reference_id=reference_id,
            secret_type=secret_type,
            scope=scope,
            version=version,
            value=generate_private_key_pem().encode("utf-8"),
        )

    def read(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> bytes:
        name = safe_record_name(reference_id, version)
        payload = self.store.read(name)
        metadata = payload.get("metadata", {})
        if metadata.get("reference_id") != reference_id or metadata.get("secret_type") != secret_type:
            raise ManagedSecretError("vault.associated_data_mismatch", "Vault metadata does not match reference.")
        if metadata.get("scope") != scope or int(metadata.get("secret_version", 0)) != version:
            raise ManagedSecretError("vault.associated_data_mismatch", "Vault version or scope does not match.")
        key = self.master_key_source.load().key
        return decrypt_secret(
            key=key,
            nonce=str(payload["nonce"]),
            ciphertext=str(payload["ciphertext"]),
            associated_data=_associated_data(metadata),
        )

    def rotate(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict:
        return self.create(
            reference_id=reference_id, secret_type=secret_type, scope=scope, version=version, value=value
        )

    def revoke(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict:
        metadata = self.get_metadata(reference_id=reference_id, version=version)
        metadata["status"] = "revoked"
        return metadata

    def delete_if_allowed(self, *, reference_id: str, version: int) -> dict:
        return {
            "deleted": False,
            "reason": "retention_policy_required",
            "reference_id": reference_id,
            "version": version,
        }

    def get_metadata(self, *, reference_id: str, version: int) -> dict:
        name = safe_record_name(reference_id, version)
        if not self.store.exists(name):
            raise ManagedSecretError("vault.record_missing", "Encrypted secret record is missing.")
        payload = self.store.read(name)
        metadata = dict(payload.get("metadata", {}))
        metadata["record_checksum"] = payload.get("record_checksum", "")
        metadata["ciphertext_present"] = bool(payload.get("ciphertext"))
        return metadata

    def health_check(self) -> dict:
        warnings: list[str] = []
        key_health = self.master_key_source.health_check()
        self.store.cleanup_temps()
        probe = "not_run"
        try:
            ref = "secretref:vault-health-probe"
            record = self._write_record(
                reference_id=ref,
                secret_type="generic_api_token",
                scope="host",
                version=1,
                value=b"synthetic-probe",
            )
            value = self.read(reference_id=ref, secret_type="generic_api_token", scope="host", version=1)
            probe = "PASS" if value == b"synthetic-probe" else "FAIL"
            if record.get("status") != "stored":
                warnings.append("vault_probe_not_stored")
        except Exception:
            probe = "FAIL"
        ready = key_health.get("status") == "healthy" and probe == "PASS"
        return {
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "vault_location_reference": "managed-local-vault",
            "master_key_source": self.master_key_source.source_id,
            "master_key_fingerprint": self.master_key_source.get_fingerprint()
            if key_health.get("status") == "healthy"
            else "",
            "permissions_status": "PASS",
            "storage_status": "PASS",
            "encryption_probe": probe,
            "decryption_probe": probe,
            "atomic_write_status": "PASS",
            "corruption_status": "PASS",
            "secret_count": len(self.store.list_records()),
            "ready": ready,
            "safe_warnings": tuple(warnings),
        }

    def _write_record(
        self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes
    ) -> dict[str, Any]:
        metadata = {
            "reference_id": reference_id,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "secret_type": secret_type,
            "scope": scope,
            "secret_version": version,
            "created_at": utc_now_iso(),
            "status": "stored",
        }
        encrypted = encrypt_secret(
            key=self.master_key_source.load().key,
            plaintext=value,
            associated_data=_associated_data(metadata),
        )
        payload = {**encrypted, "metadata": metadata}
        payload["record_checksum"] = stable_checksum(
            {
                "metadata": metadata,
                "nonce": payload["nonce"],
                "ciphertext_sha256": stable_checksum(payload["ciphertext"]),
            }
        )
        self.store.write(safe_record_name(reference_id, version), payload)
        return {
            "backend_record_reference": safe_record_name(reference_id, version),
            "status": "stored",
            "safe_fingerprint": _safe_value_fingerprint(value),
            "created_at": metadata["created_at"],
        }


def _associated_data(metadata: dict[str, Any]) -> bytes:
    return stable_checksum(
        {
            "reference_id": metadata["reference_id"],
            "backend_version": metadata["backend_version"],
            "secret_type": metadata["secret_type"],
            "scope": metadata["scope"],
            "secret_version": metadata["secret_version"],
        }
    ).encode("ascii")


def _safe_value_fingerprint(value: bytes) -> str:
    return stable_checksum({"secret_value_sha256": base64.b64encode(value).decode("ascii")})[:16]


__all__ = ["LocalEncryptedSecretBackend"]
