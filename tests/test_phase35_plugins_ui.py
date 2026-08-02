from __future__ import annotations

import unittest

from dashboard import render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35TestMixin


class Phase35PluginsUiTests(Phase35TestMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        get_plugin_runtime(self.harness.config, reset=True)

    def test_plugins_ui_shows_real_plugin_families_without_default_registry_dump(self) -> None:
        html = render_plugins_page()
        for label in ["Sources", "Transformations", "Media", "Channels", "Commerce", "Providers", "Analytics"]:
            self.assertIn(label, html)
        self.assertIn("YouTube Source", html)
        self.assertIn("Transcript retrieval not configured", html)
        self.assertIn("Video Repurpose", html)
        self.assertIn("Transcript to clip candidates", html)
        self.assertIn("Generic Product Catalog", html)
        self.assertIn("Products, catalog status", html)
        self.assertIn("Creator Commerce Repurpose", html)
        self.assertIn("Advanced Operations", html)
