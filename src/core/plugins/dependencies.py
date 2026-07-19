from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDependency:
    plugin_id: str = ""
    capability: str = ""
    min_version: str = ""
    optional: bool = False

    def __post_init__(self) -> None:
        if not self.plugin_id and not self.capability:
            raise ValueError("PluginDependency requires plugin_id or capability.")
