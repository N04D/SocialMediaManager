"""In-memory managed secret backend for tests only."""

from __future__ import annotations

from src.core.certification_evidence.models import stable_checksum, utc_now_iso
from src.core.managed_secrets.errors import ManagedSecretError
from src.core.trusted_signing.algorithms import generate_private_key_pem


class InMemoryFixtureSecretBackend:
    backend_id = "secret.in_memory_fixture"
    backend_version = "0.1.0"

    def __init__(self) -> None:
        self.records: dict[tuple[str, int], bytes] = {}

    def capabilities(self) -> dict[str, bool]:
        return {
            "create": True,
            "generate": True,
            "read": True,
            "rotate": True,
            "persistent": False,
            "production_capable": False,
        }

    def create(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict:
        self.records[(reference_id, version)] = bytes(value)
        return _metadata(reference_id, version, value)

    def generate(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict:
        if secret_type != "ed25519_private_key":
            raise ManagedSecretError("secret.generate_type", "Fixture only generates Ed25519 keys.")
        return self.create(
            reference_id=reference_id,
            secret_type=secret_type,
            scope=scope,
            version=version,
            value=generate_private_key_pem().encode("utf-8"),
        )

    def read(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> bytes:
        try:
            return self.records[(reference_id, version)]
        except KeyError as exc:
            raise ManagedSecretError("secret.fixture_missing", "Fixture secret is missing.") from exc

    def rotate(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict:
        return self.create(
            reference_id=reference_id, secret_type=secret_type, scope=scope, version=version, value=value
        )

    def revoke(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict:
        return {"status": "revoked", "reference_id": reference_id, "secret_version": version}

    def delete_if_allowed(self, *, reference_id: str, version: int) -> dict:
        return {"deleted": False}

    def get_metadata(self, *, reference_id: str, version: int) -> dict:
        return {
            "reference_id": reference_id,
            "secret_version": version,
            "value_present": (reference_id, version) in self.records,
        }

    def health_check(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "ready": True,
            "secret_count": len(self.records),
            "safe_warnings": ("fixture_backend_not_production",),
        }


def _metadata(reference_id: str, version: int, value: bytes) -> dict:
    return {
        "backend_record_reference": f"memory:{reference_id}:v{version}",
        "safe_fingerprint": stable_checksum(value.decode("latin1"))[:16],
        "status": "stored",
        "created_at": utc_now_iso(),
    }


__all__ = ["InMemoryFixtureSecretBackend"]
