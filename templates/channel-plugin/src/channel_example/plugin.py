from __future__ import annotations

from pathlib import Path

from plugin_sdk import ChannelRuntimeContext, PluginManifest, PluginRegistrationContext

from .runtime import ExampleChannelRuntime


class ExampleChannelPlugin:
    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest.from_path(Path(__file__).resolve().parents[2] / "channel.manifest.json")

    def register(self, context: PluginRegistrationContext) -> None:
        context.register_runtime_factory(self.manifest.id, self.create_runtime)

    def create_runtime(self, context: ChannelRuntimeContext) -> ExampleChannelRuntime:
        return ExampleChannelRuntime(self.manifest.id, context)


def create_plugin() -> ExampleChannelPlugin:
    return ExampleChannelPlugin()
