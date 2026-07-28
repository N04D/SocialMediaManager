"""In-memory secret store used only by deterministic tests."""

from __future__ import annotations


class EphemeralSecretStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def put(self, reference: str, value: str) -> str:
        if not reference.startswith("secretref:"):
            raise ValueError("secret reference required")
        self._secrets[reference] = value
        return reference

    def get_secret(self, secret_reference: str) -> str:
        if secret_reference not in self._secrets:
            raise KeyError(secret_reference)
        return self._secrets[secret_reference]


__all__ = ["EphemeralSecretStore"]
