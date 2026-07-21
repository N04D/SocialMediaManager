"""Read-only content facade contracts for channel plugins."""

from __future__ import annotations

from typing import Any, Protocol

from .channel import ResolvedContent


class ChannelContentFacade(Protocol):
    """Read-only content operations available to channel runtimes."""

    async def validate_requirements(self, content: ResolvedContent, requirements: Any) -> list[str]:
        """Validate content without mutating canonical content."""

    async def preview(self, content: ResolvedContent) -> str:
        """Return a safe preview string."""

    async def revision_identity(self, content: ResolvedContent) -> dict[str, str]:
        """Return stable revision identity metadata."""


__all__ = ["ChannelContentFacade", "ResolvedContent"]
