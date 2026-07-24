"""Dispatch allowlisted controller calls to an external plugin runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from .serialization import to_jsonable


class PluginRuntimeDispatcher:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.runtime: Any = None
        self.active = False

    def activate(self) -> dict[str, Any]:
        if self.runtime is None:
            self.runtime = self.plugin.create_runtime(None)
        self.active = True
        return {"status": "activated"}

    def shutdown(self) -> dict[str, Any]:
        self.active = False
        return {"status": "shutdown"}

    def ping(self) -> dict[str, Any]:
        return {"status": "ok"}

    def channel_call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.active:
            return {"status": "failed", "safe_error_code": "plugin_host.not_active"}
        target = getattr(self.runtime, name)
        result = target(params)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return {"status": "ok", "result": to_jsonable(result)}


__all__ = ["PluginRuntimeDispatcher"]
