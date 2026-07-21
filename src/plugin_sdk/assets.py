"""Media facade contracts for channel plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .channel import ResolvedMediaItem


@dataclass(frozen=True)
class MediaMaterialization:
    """Temporary materialized media available only inside a context manager."""

    path: Path
    mime_type: str
    checksum: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] | None = None


class ChannelMediaFacade(Protocol):
    """Least-privilege media materialization facade."""

    def materialize(self, selected_media: ResolvedMediaItem, purpose: str) -> Any:
        """Return an async context manager yielding MediaMaterialization."""


__all__ = ["ChannelMediaFacade", "MediaMaterialization", "ResolvedMediaItem"]
