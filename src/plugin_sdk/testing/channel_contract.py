"""Reusable channel plugin contract suite."""

from __future__ import annotations

import asyncio
from typing import Any

from ..channel import ChannelHealthRequest, ChannelRuntimeContext, PluginRegistrationContext
from ..compatibility import build_compatibility_report
from .assertions import assert_no_secrets
from .fakes import FakeClock


class ChannelPluginContractSuite:
    """Subclass in plugin tests and provide plugin_factory plus manifest_path."""

    plugin_factory: Any = None
    manifest_path: str = ""
    profiles: tuple[str, ...] = ("channel.minimal",)

    def make_plugin(self):
        if self.plugin_factory is None:
            raise AssertionError("plugin_factory is required")
        return self.plugin_factory()

    def test_manifest_compatible(self) -> None:
        report = build_compatibility_report(self.manifest_path)
        assert report.compatible, report.to_json()

    def test_registration_idempotent(self) -> None:
        plugin = self.make_plugin()
        context = PluginRegistrationContext(plugin.manifest.id)
        plugin.register(context)
        plugin.register(context)
        assert plugin.manifest.id in context.runtime_factories

    def test_health_secret_free(self) -> None:
        plugin = self.make_plugin()
        runtime = plugin.create_runtime(ChannelRuntimeContext(plugin.manifest.id, "workspace", clock=FakeClock()))
        health = asyncio.run(runtime.health_check(ChannelHealthRequest("workspace")))
        assert health.plugin_id == plugin.manifest.id
        assert_no_secrets(health)


__all__ = ["ChannelPluginContractSuite"]
