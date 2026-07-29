"""Master-key sources for the local encrypted secret backend."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from src.core.certification_evidence.models import stable_checksum
from src.core.managed_secrets.errors import ManagedSecretError

KEY_BYTES = 32


@dataclass(frozen=True)
class MasterKeyMaterial:
    source_id: str
    key: bytes
    fingerprint: str


class MasterKeySource:
    source_id: str

    def load(self) -> MasterKeyMaterial:
        raise NotImplementedError

    def get_fingerprint(self) -> str:
        return self.load().fingerprint

    def health_check(self) -> dict[str, str]:
        try:
            self.load()
            return {"source_id": self.source_id, "status": "healthy"}
        except ManagedSecretError as exc:
            return {"source_id": self.source_id, "status": "unhealthy", "safe_error_code": exc.code}


class EnvironmentMasterKeySource(MasterKeySource):
    def __init__(self, *, variable_name: str = "SMM_MANAGED_SECRET_MASTER_KEY") -> None:
        if variable_name != "SMM_MANAGED_SECRET_MASTER_KEY":
            raise ManagedSecretError("master_key.environment_name", "Environment master key name is host-owned.")
        self.source_id = "environment_master_key"
        self.variable_name = variable_name

    def load(self) -> MasterKeyMaterial:
        value = os.environ.get(self.variable_name, "")
        if not value:
            raise ManagedSecretError("master_key.missing", "Environment master key is not configured.")
        return _decode_key(value, self.source_id)


class ManagedKeyFileSource(MasterKeySource):
    def __init__(self, *, key_file: Path) -> None:
        self.source_id = "managed_key_file"
        self.key_file = key_file.resolve()

    def load(self) -> MasterKeyMaterial:
        _validate_key_file_path(self.key_file)
        value = self.key_file.read_text(encoding="utf-8").strip()
        return _decode_key(value, self.source_id)


class EphemeralTestKeySource(MasterKeySource):
    def __init__(self, key: bytes | None = None) -> None:
        self.source_id = "ephemeral_test_key"
        self._key = key or os.urandom(KEY_BYTES)

    def load(self) -> MasterKeyMaterial:
        return MasterKeyMaterial(
            source_id=self.source_id,
            key=self._key,
            fingerprint=_fingerprint(self._key),
        )


def encode_master_key(key: bytes) -> str:
    if len(key) != KEY_BYTES:
        raise ManagedSecretError("master_key.length", "Master key length is invalid.")
    return base64.urlsafe_b64encode(key).decode("ascii")


def _decode_key(value: str, source_id: str) -> MasterKeyMaterial:
    try:
        key = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise ManagedSecretError("master_key.encoding", "Master key encoding is invalid.") from exc
    if len(key) != KEY_BYTES:
        raise ManagedSecretError("master_key.length", "Master key length is invalid.")
    return MasterKeyMaterial(source_id=source_id, key=key, fingerprint=_fingerprint(key))


def _fingerprint(key: bytes) -> str:
    return stable_checksum({"master_key_sha256": base64.b64encode(key).decode("ascii")})[:24]


def _validate_key_file_path(path: Path) -> None:
    parts = set(path.parts)
    if "content" in parts or "drafts" in parts:
        raise ManagedSecretError("master_key.user_owned_path", "Managed key file cannot live in user-owned paths.")
    if not path.exists():
        raise ManagedSecretError("master_key.missing", "Managed key file is missing.")
    if path.is_symlink():
        raise ManagedSecretError("master_key.symlink", "Managed key file cannot be a symlink.")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ManagedSecretError("master_key.permissions", "Managed key file must not be group/world readable.")


__all__ = [
    "EnvironmentMasterKeySource",
    "EphemeralTestKeySource",
    "ManagedKeyFileSource",
    "MasterKeyMaterial",
    "MasterKeySource",
    "encode_master_key",
]
