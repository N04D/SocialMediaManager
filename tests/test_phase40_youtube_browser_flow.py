import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class YouTubeBrowserFlowTests(unittest.TestCase):
    def test_plugin_surface_contains_review_and_safe_states(self):
        harness = Phase35Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        page = render_plugins_page()
        self.assertIn("Connect", page)
        self.assertIn("Test connection", page)
        self.assertIn("YouTube", page)

    def test_real_chromium_review_is_responsive(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"Playwright unavailable: {exc}")
        html = (
            "<!doctype html><html><head><style>body{margin:0;overflow-wrap:anywhere}.panel,.source-context-box{padding:12px;border:1px solid #ccc;min-width:0}.tabs,.actions{display:flex;flex-wrap:wrap;gap:8px}.workspace-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.owned-workspace,.owned-workspace *{min-width:0}.owned-workspace{max-width:100%;overflow-x:hidden}.owned-workspace .workspace-grid{max-width:100%}@media(max-width:840px){.owned-workspace .workspace-grid{grid-template-columns:minmax(0,1fr)}.owned-workspace .panel{max-width:100%;overflow-x:auto}}</style></head><body>"
            + render_plugins_page()
            + render_owned_publication_workspace_page()
            + "</body></html>"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in ((1440, 900), (1280, 800), (768, 1024), (390, 844)):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_content(html)
                    self.assertIn("Publish to YouTube", page.text_content("body") or "")
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                    )
                    page.close()
            finally:
                browser.close()
