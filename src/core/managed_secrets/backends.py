"""Managed secret backend protocol."""

from __future__ import annotations

from typing import Protocol


class ManagedSecretBackend(Protocol):
    backend_id: str
    backend_version: str

    def capabilities(self) -> dict[str, bool]: ...

    def create(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict: ...

    def generate(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict: ...

    def read(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> bytes: ...

    def rotate(self, *, reference_id: str, secret_type: str, scope: str, version: int, value: bytes) -> dict: ...

    def revoke(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> dict: ...

    def delete_if_allowed(self, *, reference_id: str, version: int) -> dict: ...

    def get_metadata(self, *, reference_id: str, version: int) -> dict: ...

    def health_check(self) -> dict: ...


__all__ = ["ManagedSecretBackend"]
