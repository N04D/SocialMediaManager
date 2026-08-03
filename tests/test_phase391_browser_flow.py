import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class Phase391BrowserFlowTests(unittest.TestCase):
    def test_real_chromium_shows_evidence_labels_without_pii(self):
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
            ".panel,.card{min-width:0;overflow-wrap:anywhere;}table{display:block;max-width:100%;overflow-x:auto;}"
            ".actions,.tabs{display:flex;flex-wrap:wrap;gap:8px;}pre{white-space:pre-wrap;}"
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
                    self.assertIn("Commerce outcomes", body)
                    self.assertIn("Sync outcomes", body)
                    self.assertIn("Read-only adapter", body)
                    self.assertNotIn("private@example.test", body)
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                    )
                    page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
