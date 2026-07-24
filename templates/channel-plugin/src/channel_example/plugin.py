from __future__ import annotations

from pathlib import Path

from plugin_sdk import ChannelRuntimeContext, PluginManifest, PluginRegistrationContext

from .runtime import ExampleChannelRuntime


class ExampleChannelPlugin:
    @property
    def manifest(self) -> PluginManifest:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "channel.manifest.json"
            if candidate.exists():
                return PluginManifest.from_path(candidate)
        raise RuntimeError("channel manifest is missing")

    def register(self, context: PluginRegistrationContext) -> None:
        context.register_runtime_factory(self.manifest.id, self.create_runtime)

    def create_runtime(self, context: ChannelRuntimeContext) -> ExampleChannelRuntime:
        return ExampleChannelRuntime(self.manifest.id, context)


def create_plugin() -> ExampleChannelPlugin:
    return ExampleChannelPlugin()
