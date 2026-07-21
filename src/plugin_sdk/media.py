"""Media plugin public interface."""

from __future__ import annotations

from typing import Any, Protocol


class MediaPlugin(Protocol):
    """Minimal media plugin lifecycle contract."""

    @property
    def manifest(self) -> Any: ...
    def register(self, context: Any) -> None: ...


__all__ = ["MediaPlugin"]
