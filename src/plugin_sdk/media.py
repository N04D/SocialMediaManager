from __future__ import annotations

from typing import Protocol

from src.core.plugins import PluginContext


class MediaPlugin(Protocol):
    def initialize(self, context: PluginContext) -> None:
        ...
