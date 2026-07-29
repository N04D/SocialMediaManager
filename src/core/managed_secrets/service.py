"""Application service for managed secrets and production composition."""

from __future__ import annotations

import os
from pathlib import Path

from src.providers.secrets.environment import EnvironmentReadOnlySecretBackend
from src.providers.secrets.local_encrypted import EnvironmentMasterKeySource, LocalEncryptedSecretBackend

from .facade import ManagedSecretFacade


def configured_managed_secret_facade(*, database_path: Path | None = None) -> ManagedSecretFacade:
    backend_id = os.environ.get("SMM_MANAGED_SECRET_BACKEND", "")
    if backend_id == "local_encrypted":
        vault = Path(os.environ.get("SMM_MANAGED_SECRET_VAULT_DIR", "studio_data/managed_secret_vault"))
        return ManagedSecretFacade(
            database_path=database_path,
            backend=LocalEncryptedSecretBackend(vault_dir=vault, master_key_source=EnvironmentMasterKeySource()),
        )
    if backend_id == "environment_read_only":
        return ManagedSecretFacade(database_path=database_path, backend=EnvironmentReadOnlySecretBackend({}))
    return ManagedSecretFacade(database_path=database_path, backend=None)


class PurposeBoundSecretReader:
    def __init__(self, facade: ManagedSecretFacade, *, purpose: str, consumer: str) -> None:
        self.facade = facade
        self.purpose = purpose
        self.consumer = consumer

    def get_secret(self, secret_reference: str) -> str:
        return self.facade.get_secret(secret_reference, purpose=self.purpose, consumer=self.consumer)


__all__ = ["PurposeBoundSecretReader", "configured_managed_secret_facade"]
