"""Fixtures for trusted signer lifecycle tests."""

from __future__ import annotations

from src.core.trusted_signing.algorithms import generate_private_key_pem

from .ephemeral_secret_store import EphemeralSecretStore


def signer_secret_fixture(reference: str = "secretref:signer/phase29") -> tuple[EphemeralSecretStore, str]:
    store = EphemeralSecretStore()
    store.put(reference, generate_private_key_pem())
    return store, reference


__all__ = ["signer_secret_fixture"]
