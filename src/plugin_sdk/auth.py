"""Authentication and secret facade contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SecretReference:
    """Opaque secret reference safe for records and logs."""

    reference: str
    version: int = 1
    created_at: datetime | None = None

    def __repr__(self) -> str:
        return f"SecretReference(reference='<redacted>', version={self.version})"


class PluginSecretService(Protocol):
    """Minimal namespace-bound secret service for plugins."""

    async def put_secret(
        self,
        plugin_id: str,
        workspace_id: str,
        account_id: str,
        purpose: str,
        value: str,
    ) -> SecretReference: ...

    async def get_secret(self, reference: SecretReference) -> str: ...
    async def revoke_secret(self, reference: SecretReference) -> None: ...
    async def has_secret(self, reference: SecretReference) -> bool: ...


__all__ = ["PluginSecretService", "SecretReference"]
