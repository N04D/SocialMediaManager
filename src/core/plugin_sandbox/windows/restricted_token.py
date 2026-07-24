"""Windows restricted token metadata."""

from __future__ import annotations


def restricted_token_available() -> bool:
    return False


__all__ = ["restricted_token_available"]
