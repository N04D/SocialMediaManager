"""Fixtures for managed secret tests."""

from __future__ import annotations

from pathlib import Path

from src.core.managed_secrets.facade import ManagedSecretFacade
from src.providers.secrets.local_encrypted import EphemeralTestKeySource, LocalEncryptedSecretBackend


def encrypted_facade(database_path: Path, vault_dir: Path) -> ManagedSecretFacade:
    return ManagedSecretFacade(
        database_path=database_path,
        backend=LocalEncryptedSecretBackend(vault_dir=vault_dir, master_key_source=EphemeralTestKeySource()),
    )


__all__ = ["encrypted_facade"]
