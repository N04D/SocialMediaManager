from __future__ import annotations

import unittest

from playwright.sync_api import expect, sync_playwright

from tests.owned_publication_browser_certification import DashboardBrowserServer, chromium_executable


class OwnedPublicationBrowserConcurrencyPhase231Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = DashboardBrowserServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_two_browser_contexts_show_conflict_without_overwrite(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
            try:
                context_a = browser.new_context()
                context_b = browser.new_context()
                page_a = context_a.new_page()
                page_b = context_b.new_page()
                page_a.goto(self.server.base_url + "/content/new")
                page_b.goto(self.server.base_url + "/content/new")
                expect(page_a.locator("#owned-title")).to_have_value("Owned Funnel Launch")
                expect(page_b.locator("#owned-title")).to_have_value("Owned Funnel Launch")

                page_a.locator("#owned-title").fill("Editor A title")
                expect(page_a.locator("#autosave-status")).to_contain_text("saved", timeout=5000)
                self.assertEqual(self.server.repository.get_draft("content-owned-1").title, "Editor A title")

                page_b.locator("#owned-title").fill("Editor B stale overwrite")
                expect(page_b.locator("#conflict-status")).to_contain_text("Conflict", timeout=5000)
                expect(page_b.locator("#autosave-status")).to_contain_text("conflict")
                self.assertEqual(self.server.repository.get_draft("content-owned-1").title, "Editor A title")
                page_b.reload()
                expect(page_b.locator("#owned-title")).to_have_value("Editor A title")
                revisions = self.server.repository.list_revisions("content-owned-1")
                self.assertEqual(revisions[-1].id, "content-owned-1-rev-1")
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
