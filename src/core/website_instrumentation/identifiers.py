"""Opaque instrumentation identifiers."""

from __future__ import annotations

import hmac

from .models import OPAQUE_RE, stable_checksum


def opaque_id(workspace_id: str, id_type: str, binding: str) -> str:
    digest = stable_checksum({"workspace": workspace_id, "type": id_type, "binding": binding})[:24]
    return f"smm_{id_type}_{digest}"


def validate_opaque_id(value: str, expected_type: str = "") -> bool:
    if not OPAQUE_RE.match(value):
        return False
    if expected_type:
        return hmac.compare_digest(value.split("_", maxsplit=2)[1], expected_type)
    return True


__all__ = ["opaque_id", "validate_opaque_id"]
