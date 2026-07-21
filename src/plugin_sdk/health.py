"""Health and integrity models for Plugin SDK v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .channel import ChannelHealth


@dataclass(frozen=True)
class PluginIntegrityFinding:
    """Read-only integrity finding emitted by plugin checks."""

    code: str
    severity: str
    plugin_id: str
    account_id: str = ""
    resource_type: str = ""
    resource_id: str = ""
    safe_message: str = ""
    repairable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["ChannelHealth", "PluginIntegrityFinding"]
