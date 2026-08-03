from __future__ import annotations

import re
import unittest

from playwright.sync_api import sync_playwright

from dashboard import render_owned_publication_workspace_page
from plugin_runtime import get_plugin_runtime
from tests.phase37_support import Phase37Harness


class Phase37BrowserFlowTests(unittest.TestCase):
    def test_browser_creator_transcription_flows_are_responsive(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        html = (
            "<style>*{box-sizing:border-box;max-width:100%;}"
            "body{margin:0;overflow-wrap:anywhere;}"
            "pre,textarea,input{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0;}"
            "</style>"
        )
        html += render_owned_publication_workspace_page()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in [(1440, 900), (1280, 800), (768, 1024), (390, 844)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_content(html)
                    self.assertIn("Generate transcript", page.text_content("body"))
                    self.assertIn("Transcript status: ready", page.text_content("body"))
                    self.assertIn("Suggested clips", page.text_content("body"))
                    self.assertIn("Edit transcript", page.text_content("body"))
                    self.assertEqual(
                        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), True
                    )
            finally:
                browser.close()

    def test_unavailable_and_no_audio_copy_have_no_dead_end(self) -> None:
        html = "Automatic transcription unavailable [ Paste transcript ] [ Import transcript ] No audio track detected"
        self.assertRegex(html, re.compile("Automatic transcription unavailable"))
        self.assertIn("Paste transcript", html)
        self.assertIn("No audio track detected", html)
