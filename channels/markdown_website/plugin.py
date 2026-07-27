"""Plugin object for the built-in Markdown Website channel."""

from __future__ import annotations

from pathlib import Path

from plugin_sdk import ChannelRuntimeContext, PluginManifest, PluginRegistrationContext

from .runtime import MarkdownWebsiteChannelRuntime


class MarkdownWebsiteChannelPlugin:
    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest.from_path(Path(__file__).with_name("plugin.manifest.json"))

    def register(self, context: PluginRegistrationContext) -> None:
        context.register_runtime_factory(self.manifest.id, self.create_runtime)

    def create_runtime(self, context: ChannelRuntimeContext) -> MarkdownWebsiteChannelRuntime:
        return MarkdownWebsiteChannelRuntime()


def create_plugin() -> MarkdownWebsiteChannelPlugin:
    return MarkdownWebsiteChannelPlugin()
