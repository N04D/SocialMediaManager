from __future__ import annotations

import unittest

from dashboard import render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase37_support import Phase37Harness


class Phase37ProviderUiTests(unittest.TestCase):
    def test_plugins_providers_shows_local_transcription_without_dump_first(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        html = render_plugins_page()
        self.assertIn("Providers", html)
        self.assertIn("Local Transcription", html)
        self.assertIn("Transcription", html)
        self.assertIn("Supported inputs", html)
