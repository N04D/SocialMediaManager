"""AES-GCM helpers for the local encrypted secret backend."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.core.managed_secrets.errors import ManagedSecretError

NONCE_BYTES = 12


def encrypt_secret(*, key: bytes, plaintext: bytes, associated_data: bytes) -> dict[str, str]:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return {
        "algorithm": "AES-256-GCM",
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_secret(*, key: bytes, nonce: str, ciphertext: str, associated_data: bytes) -> bytes:
    try:
        nonce_bytes = base64.urlsafe_b64decode(nonce.encode("ascii"))
        ciphertext_bytes = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        return AESGCM(key).decrypt(nonce_bytes, ciphertext_bytes, associated_data)
    except Exception as exc:
        raise ManagedSecretError("vault.gcm_authentication_failed", "Encrypted secret integrity check failed.") from exc


__all__ = ["decrypt_secret", "encrypt_secret"]
