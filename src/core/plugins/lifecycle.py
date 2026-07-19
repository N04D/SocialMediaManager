from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class PluginContext:
    plugin_id: str
    config: dict[str, Any] = field(default_factory=dict)
    data_dir: Path | None = None
    services: dict[str, Any] = field(default_factory=dict)


class PluginLifecycle(Protocol):
    def validate(self, context: PluginContext) -> None: ...

    def install(self, context: PluginContext) -> None: ...

    def initialize(self, context: PluginContext) -> None: ...

    def health_check(self, context: PluginContext) -> dict[str, Any]: ...

    def start(self, context: PluginContext) -> None: ...

    def stop(self, context: PluginContext) -> None: ...

    def uninstall(self, context: PluginContext) -> None: ...
