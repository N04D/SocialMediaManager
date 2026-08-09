from __future__ import annotations

import re

from .errors import RuntimeValidationError

NAMESPACED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$")
RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_namespaced_id(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not NAMESPACED_ID_RE.match(normalized):
        raise RuntimeValidationError(
            "runtime.invalid_namespaced_id",
            f"{field_name} must be a dot-namespaced identifier.",
            {"field": field_name, "value": value},
        )
    return normalized


def validate_runtime_id(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not RUNTIME_ID_RE.match(normalized):
        raise RuntimeValidationError(
            "runtime.invalid_id",
            f"{field_name} must be a non-empty runtime identifier.",
            {"field": field_name, "value": value},
        )
    return normalized
