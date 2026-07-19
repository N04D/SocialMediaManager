from __future__ import annotations

from typing import Protocol

from src.core.plugins import PluginContext


class ChannelPlugin(Protocol):
    def initialize(self, context: PluginContext) -> None:
        ...
