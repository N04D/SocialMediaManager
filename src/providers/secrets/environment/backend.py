"""Read-only environment managed secret backend."""

from __future__ import annotations

import os

from src.core.managed_secrets.errors import ManagedSecretError


class EnvironmentReadOnlySecretBackend:
    backend_id = "secret.environment_read_only"
    backend_version = "0.1.0"

    def __init__(self, bindings: dict[str, str]) -> None:
        self.bindings = dict(bindings)

    def capabilities(self) -> dict[str, bool]:
        return {"create": False, "generate": False, "read": True, "rotate": False, "persistent": False}

    def create(self, **_: object) -> dict:
        raise ManagedSecretError("secret.environment_read_only", "Environment backend cannot create secrets.")

    def generate(self, **_: object) -> dict:
        raise ManagedSecretError("secret.environment_read_only", "Environment backend cannot generate secrets.")

    def read(self, *, reference_id: str, secret_type: str, scope: str, version: int) -> bytes:
        variable = self.bindings.get(reference_id, "")
        if not variable:
            raise ManagedSecretError("secret.environment_binding_missing", "Environment secret binding is missing.")
        value = os.environ.get(variable, "")
        if not value:
            raise ManagedSecretError("secret.environment_missing", "Environment secret value is missing.")
        return value.encode("utf-8")

    def rotate(self, **_: object) -> dict:
        raise ManagedSecretError("secret.environment_read_only", "Environment backend cannot rotate secrets.")

    def revoke(self, **_: object) -> dict:
        return {"status": "revoked_in_metadata_only"}

    def delete_if_allowed(self, **_: object) -> dict:
        return {"deleted": False}

    def get_metadata(self, *, reference_id: str, version: int) -> dict:
        return {"reference_id": reference_id, "secret_version": version, "value_present": reference_id in self.bindings}

    def health_check(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "ready": True,
            "safe_warnings": (),
        }


__all__ = ["EnvironmentReadOnlySecretBackend"]
