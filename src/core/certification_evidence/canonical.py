"""Canonical JSON serialization for certification evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import CertificationEvidenceError

FORBIDDEN_TEXT_MARKERS = (
    "BEGIN PRIVATE KEY",
    "authorization:",
    "content/",
    "drafts/",
)


def canonical_data(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(key): canonical_data(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_data(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Path):
        raise CertificationEvidenceError("certification.absolute_path", "Paths are not canonical evidence values.")
    if isinstance(value, float):
        return float(format(value, ".12g"))
    if isinstance(value, str):
        _validate_safe_text(value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    payload = canonical_data(value)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    _validate_safe_text(encoded.decode("utf-8"))
    return encoded


def canonical_json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _validate_safe_text(text: str) -> None:
    lowered = text.lower()
    for marker in FORBIDDEN_TEXT_MARKERS:
        if marker.lower() in lowered:
            raise CertificationEvidenceError(
                "certification.forbidden_data", "Canonical evidence contains forbidden data."
            )
    if "://" in text and "smm-staging.test" not in text and "example.test" not in text:
        raise CertificationEvidenceError(
            "certification.external_reference", "Canonical evidence contains an unsafe external reference."
        )


__all__ = ["canonical_data", "canonical_json_bytes", "canonical_json_text"]
