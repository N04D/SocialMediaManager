from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class Phase39BrowserFlowTests(unittest.TestCase):
    def test_real_chromium_woocommerce_ui_is_responsive_and_secret_safe(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"Playwright unavailable: {exc}")
        harness = Phase35Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        html = (
            "<!doctype html><html><head><style>"
            "*{box-sizing:border-box;max-width:100%;}body{margin:0;overflow-wrap:anywhere;}"
            ".workspace-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}"
            ".panel,.source-context-box{padding:12px;border:1px solid #ccc;min-width:0;overflow-wrap:anywhere;}"
            ".tabs,.actions{display:flex;flex-wrap:wrap;gap:8px;}pre{white-space:pre-wrap;}"
            "</style></head><body>"
            + render_plugins_page()
            + render_owned_publication_workspace_page()
            + "</body></html>"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in [(1440, 900), (1280, 800), (768, 1024), (390, 844)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_content(html)
                    body = page.text_content("body") or ""
                    self.assertIn("WooCommerce", body)
                    self.assertIn("Configure", body)
                    self.assertIn("Test connection", body)
                    self.assertIn("Sabr T-shirt", body)
                    self.assertIn("From WooCommerce", body)
                    self.assertNotIn("ck_test_key", body)
                    self.assertNotIn("cs_test_secret", body)
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                    )
                    page.close()
            finally:
                browser.close()
