"""Secret purpose helpers."""

from __future__ import annotations

from .errors import ManagedSecretError
from .models import SECRET_PURPOSES


def validate_purpose(purpose: str) -> None:
    if purpose not in SECRET_PURPOSES:
        raise ManagedSecretError("secret.purpose_unknown", "Secret purpose is not registered.")


def validate_purpose_allowed(purpose: str, allowed: tuple[str, ...]) -> None:
    validate_purpose(purpose)
    if purpose not in allowed:
        raise ManagedSecretError("secret_purpose_not_allowed", "Secret purpose is not allowed for this reference.")


__all__ = ["validate_purpose", "validate_purpose_allowed"]
