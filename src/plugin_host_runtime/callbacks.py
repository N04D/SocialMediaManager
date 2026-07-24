"""Child-side callback client placeholder.

External plugins receive SDK facades from the child runtime in later hardening;
phase 19 keeps callbacks explicit and JSON-only.
"""

from __future__ import annotations

from typing import Any


class HostCallbackClient:
    def __init__(self, context_id: str = "") -> None:
        self.context_id = context_id
        self.history: list[dict[str, Any]] = []

    def record(self, method: str, params: dict[str, Any]) -> None:
        self.history.append({"method": method, "params": params})


__all__ = ["HostCallbackClient"]
