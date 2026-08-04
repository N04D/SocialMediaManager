import unittest

from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class YouTubeCapabilityTests(unittest.TestCase):
    def test_registry_discovers_youtube_destination(self):
        harness = Phase35Harness()
        self.addCleanup(harness.close)
        runtime = get_plugin_runtime(harness.config, reset=True, strict=False)
        plugin = runtime.registry.get("channel.youtube")
        self.assertIsNotNone(plugin)
        self.assertIn("channel.publish.short_video", plugin.capabilities)
        self.assertIsNotNone(runtime.runtimes["channel.youtube"].service("channel_runtime"))
