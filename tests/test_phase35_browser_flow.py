from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35TestMixin


class Phase35BrowserFlowTests(Phase35TestMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        get_plugin_runtime(self.harness.config, reset=True)

    def test_real_chromium_plugins_and_content_flows_are_responsive(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - environment guard
            self.skipTest(f"Playwright unavailable: {exc}")
        html = (
            "<!doctype html><html><head><style>"
            "*{box-sizing:border-box;max-width:100%;}body{margin:0;overflow-wrap:anywhere;}"
            ".workspace-grid,.editor-two-up{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}"
            ".panel,.card{padding:12px;border:1px solid #ccc;}"
            ".tabs,.pill-row,.actions{display:flex;flex-wrap:wrap;gap:8px;}pre{white-space:pre-wrap;}"
            "textarea,input,select{width:100%;}"
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
                    self.assertIn("New content", page.text_content("body") or "")
                    self.assertIn("YouTube URL or video ID", page.text_content("body") or "")
                    self.assertIn("Primary source", page.text_content("body") or "")
                    self.assertIn("Sabr T-shirt", page.text_content("body") or "")
                    self.assertIn("Video Repurpose", page.text_content("body") or "")
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                    )
                    self.assertFalse(overflow, f"horizontal overflow at {width}x{height}")
                    page.close()
            finally:
                browser.close()
