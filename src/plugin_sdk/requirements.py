"""Requirement contracts exposed through the public SDK."""

from __future__ import annotations

from typing import Any, Protocol

from src.core.content import ChannelContentRequirements
from src.core.media import ChannelMediaRequirements


class ChannelRequirementResolver(Protocol):
    """Resolve static or account-bound channel requirements."""

    async def resolve_content_requirements(
        self, workspace_id: str, channel_account_id: str = ""
    ) -> ChannelContentRequirements:
        """Return content requirements for an account or channel."""

    async def resolve_media_requirements(
        self, workspace_id: str, channel_account_id: str = ""
    ) -> ChannelMediaRequirements:
        """Return media requirements for an account or channel."""

    async def freshness(self, workspace_id: str, channel_account_id: str = "") -> dict[str, Any]:
        """Return freshness metadata for dynamic requirement snapshots."""


__all__ = [
    "ChannelContentRequirements",
    "ChannelMediaRequirements",
    "ChannelRequirementResolver",
]
