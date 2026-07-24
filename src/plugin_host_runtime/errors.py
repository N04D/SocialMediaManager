"""Child runtime errors."""

from __future__ import annotations


class PluginRuntimeError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


__all__ = ["PluginRuntimeError"]
