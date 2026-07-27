from __future__ import annotations

import unittest

from playwright.sync_api import expect, sync_playwright

from tests.owned_publication_browser_certification import (
    DashboardBrowserServer,
    chromium_executable,
    expect_no_sensitive_output,
)


class OwnedPublicationRealBrowserPhase231Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = DashboardBrowserServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_real_browser_full_article_to_funnel_flow_survives_restart(self) -> None:
        executable = chromium_executable()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page()
                page.goto(self.server.base_url + "/content/new")
                expect(page.get_by_role("heading", name="Article composer")).to_be_visible()
                self.assertEqual(page.get_by_role("heading", name="Article composer").count(), 1)
                title = page.locator("#owned-title")
                body = page.locator("#owned-body")
                title.fill("Browser Certified Article")
                body.fill("# Browser Certified\n\nA durable browser autosave proof.")
                page.locator("#owned-author").fill("Editor A")
                page.locator("#owned-tags").fill("browser, certification")
                page.locator("#owned-seo").fill("Certified SEO description")
                page.locator("#owned-cta").fill("Start certification")
                expect(page.locator("#autosave-status")).to_contain_text("saved", timeout=5000)
                autosaves = page.evaluate("window.__ownedPublicationAutosaveRequests")
                self.assertLessEqual(autosaves, 4)
                draft = self.server.repository.get_draft("content-owned-1")
                self.assertEqual(draft.title, "Browser Certified Article")
                self.assertEqual(draft.author, "Editor A")
                self.assertEqual(draft.tags, ("browser", "certification"))

                page.reload()
                expect(page.locator("#owned-title")).to_have_value("Browser Certified Article")
                expect(page.locator("#owned-author")).to_have_value("Editor A")

                page.locator('[role="tab"]').first.focus()
                page.keyboard.press("ArrowRight")
                expect(page.get_by_role("tab", name="LinkedIn")).to_have_attribute("aria-selected", "true")
                page.locator("#create-revision").click()
                expect(page.locator("#autosave-status")).to_contain_text("Revision created", timeout=5000)
                page.locator("#create-plan").click()
                expect(page.locator("#autosave-status")).to_contain_text("Publication plan created", timeout=5000)
                expect(page.get_by_role("heading", name="Dependency graph")).to_be_visible()
                expect(page.get_by_role("cell", name="target-linkedin").first).to_be_visible()
                expect(page.get_by_role("heading", name="Execution timeline")).to_be_visible()
                expect(page.get_by_role("heading", name="Evidence viewer")).to_be_visible()
                page.locator("#reconciliation-check").click()
                expect(page.locator("#reconciliation-status")).to_contain_text("Read-only reconciliation", timeout=5000)
                expect(page.get_by_role("heading", name="Funnel dashboard")).to_be_visible()

                self.assertFalse(page.evaluate("window.__unsafe === true"))
                unsafe = page.locator("#unsafe-preview-fixture")
                self.assertEqual(unsafe.locator("script").count(), 0)
                self.assertEqual(unsafe.locator("iframe").count(), 0)
                self.assertEqual(unsafe.locator("[onerror]").count(), 0)
                self.assertEqual(unsafe.locator('a[href^="javascript:"]').count(), 0)
                expect(unsafe).to_contain_text("Normal")
                self.assertGreater(page.locator("label").count(), 8)
                expect(page.locator("#autosave-status")).to_have_attribute("aria-live", "polite")
                self.assertTrue(page.locator("#publish-plan").is_disabled())
                expect_no_sensitive_output(page.content())

                self.server.restart()
                page.goto(self.server.base_url + "/content/new")
                expect(page.locator("#owned-title")).to_have_value("Browser Certified Article")
                self.assertGreaterEqual(len(self.server.repository.list_revisions("content-owned-1")), 2)
                self.assertGreaterEqual(len(self.server.repository.list_reconciliation()), 1)
                funnel = page.goto(self.server.base_url + "/funnels/content-owned-1")
                self.assertIsNotNone(funnel)
                expect(page.get_by_role("heading", name="Funnel dashboard")).to_be_visible()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
