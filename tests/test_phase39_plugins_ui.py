from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class Phase39PluginsUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)
        get_plugin_runtime(self.harness.config, reset=True, strict=False)

    def test_plugins_commerce_ui_shows_woocommerce_without_secrets(self) -> None:
        html = render_plugins_page()
        self.assertIn("WooCommerce", html)
        self.assertIn("Test connection", html)
        self.assertIn("Sync products", html)
        self.assertIn("Products synced", html)
        self.assertIn("managed secrets", html)
        self.assertNotIn("ck_test_key", html)
        self.assertNotIn("cs_test_secret", html)

    def test_content_workspace_shows_woocommerce_product_context(self) -> None:
        html = render_owned_publication_workspace_page()
        self.assertIn("From WooCommerce", html)
        self.assertIn("Product details", html)
        self.assertIn("Use in campaign", html)
