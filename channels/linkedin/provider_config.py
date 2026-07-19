from __future__ import annotations

from typing import Any

from channel_store import get_channel_connection


def preferred_browser_provider_id(config: Any, *, channel_id: str = "linkedin") -> str:
    connection = get_channel_connection(channel_id)
    if connection and connection.browser_provider_id:
        return connection.browser_provider_id
    return str(getattr(config, "linkedin_browser_provider_id", "") or "")
