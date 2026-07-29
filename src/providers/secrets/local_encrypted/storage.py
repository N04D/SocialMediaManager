"""Crash-safe record storage for encrypted secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.core.certification_evidence.models import stable_checksum
from src.core.managed_secrets.errors import ManagedSecretError


def safe_record_name(reference_id: str, version: int) -> str:
    suffix = stable_checksum({"reference": reference_id, "version": version})[:32]
    return f"{suffix}.secret.json"


class VaultRecordStore:
    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir.resolve()
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._validate_vault_dir()

    def write(self, name: str, payload: dict[str, Any]) -> Path:
        self._validate_name(name)
        target = self.vault_dir / name
        tmp = self.vault_dir / f".{name}.tmp"
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with tmp.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, target)
        return target

    def read(self, name: str) -> dict[str, Any]:
        self._validate_name(name)
        path = self.vault_dir / name
        if path.is_symlink():
            raise ManagedSecretError("vault.symlink", "Vault record cannot be a symlink.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManagedSecretError("vault.record_truncated", "Vault record is not valid JSON.") from exc

    def exists(self, name: str) -> bool:
        self._validate_name(name)
        return (self.vault_dir / name).exists()

    def list_records(self) -> list[str]:
        return sorted(path.name for path in self.vault_dir.glob("*.secret.json") if not path.is_symlink())

    def cleanup_temps(self) -> int:
        deleted = 0
        for path in self.vault_dir.glob(".*.tmp"):
            if not path.is_symlink():
                path.unlink(missing_ok=True)
                deleted += 1
        return deleted

    def _validate_vault_dir(self) -> None:
        parts = set(self.vault_dir.parts)
        if "content" in parts or "drafts" in parts:
            raise ManagedSecretError("vault.user_owned_path", "Vault cannot live in user-owned paths.")
        if self.vault_dir.is_symlink():
            raise ManagedSecretError("vault.symlink", "Vault directory cannot be a symlink.")
        mode = self.vault_dir.stat().st_mode & 0o777
        if mode & 0o077:
            try:
                self.vault_dir.chmod(0o700)
            except OSError as exc:
                raise ManagedSecretError("vault.permissions", "Vault permissions are too broad.") from exc

    @staticmethod
    def _validate_name(name: str) -> None:
        if "/" in name or "\\" in name or ".." in name or not name.endswith(".secret.json"):
            raise ManagedSecretError("vault.path_traversal", "Vault record name is not managed.")


__all__ = ["VaultRecordStore", "safe_record_name"]
