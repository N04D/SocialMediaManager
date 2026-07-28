"""Ed25519 helpers backed by the established cryptography library."""

from __future__ import annotations

import base64
import hashlib

from .errors import TrustedSigningError

try:  # pragma: no cover - exercised when dependency is absent on a host.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover
    InvalidSignature = None  # type: ignore[assignment]
    serialization = None  # type: ignore[assignment]
    Ed25519PrivateKey = None  # type: ignore[assignment]
    Ed25519PublicKey = None  # type: ignore[assignment]


def ed25519_available() -> bool:
    return Ed25519PrivateKey is not None and serialization is not None


def generate_private_key_pem() -> str:
    if not ed25519_available():
        raise TrustedSigningError("signer.crypto_unavailable", "Ed25519 signing dependency is not available.")
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def public_key_from_private_pem(private_pem: str) -> str:
    key = _load_private(private_pem)
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def fingerprint_public_key(public_key_pem: str) -> str:
    return hashlib.sha256(public_key_pem.encode("utf-8")).hexdigest()


def sign_ed25519(private_pem: str, payload: bytes) -> str:
    return base64.b64encode(_load_private(private_pem).sign(payload)).decode("ascii")


def verify_ed25519(public_key_pem: str, payload: bytes, signature: str) -> bool:
    if not ed25519_available():
        return False
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(base64.b64decode(signature.encode("ascii")), payload)
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


def validate_key_pair(private_pem: str, public_key_pem: str) -> bool:
    probe = b"smm-certification-signer-probe-v1"
    return verify_ed25519(public_key_pem, probe, sign_ed25519(private_pem, probe))


def _load_private(private_pem: str):
    if not ed25519_available():
        raise TrustedSigningError("signer.crypto_unavailable", "Ed25519 signing dependency is not available.")
    try:
        key = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
    except (TypeError, ValueError) as exc:
        raise TrustedSigningError("signer.invalid_key", "Signer private key format is invalid.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise TrustedSigningError("signer.algorithm", "Signer key is not Ed25519.")
    return key


__all__ = [
    "ed25519_available",
    "fingerprint_public_key",
    "generate_private_key_pem",
    "public_key_from_private_pem",
    "sign_ed25519",
    "validate_key_pair",
    "verify_ed25519",
]
