"""JSON-only serialization helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {key: to_jsonable(item) for key, item in value.__dict__.items() if not key.startswith("_")}
    return str(value)


__all__ = ["to_jsonable"]
