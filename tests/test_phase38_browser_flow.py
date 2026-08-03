from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page


class Phase38BrowserFlowTests(unittest.TestCase):
    def test_real_chromium_clip_recommendations_are_responsive(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"Playwright unavailable: {exc}")
        html = (
            "<!doctype html><html><head><style>"
            "*{box-sizing:border-box;max-width:100%;}body{margin:0;overflow-wrap:anywhere;}"
            ".workspace-grid,.editor-two-up{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}"
            ".panel,.source-context,.source-context-box{padding:12px;border:1px solid #ccc;min-width:0;overflow-wrap:anywhere;}"
            ".tabs,.actions{display:flex;flex-wrap:wrap;gap:8px;}video{width:180px;aspect-ratio:9/16;background:#111;}"
            "pre,textarea,input,select{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0;width:100%;}"
            "</style></head><body>" + render_owned_publication_workspace_page() + "</body></html>"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in [(1440, 900), (1280, 800), (768, 1024), (390, 844)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_content(html)
                    body = page.text_content("body") or ""
                    self.assertIn("Recommended", body)
                    self.assertIn("Why this clip?", body)
                    self.assertIn("Use clip", body)
                    self.assertIn("Rendered clips", body)
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                    )
                    page.close()
            finally:
                browser.close()
