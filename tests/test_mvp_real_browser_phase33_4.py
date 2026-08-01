from __future__ import annotations

import unittest

from playwright.sync_api import expect, sync_playwright

import mvp_dashboard
from tests.owned_publication_browser_certification import chromium_executable
from tests.phase331_support import chromium_available
from tests.phase334_support import Phase334TestCase


class MVPRealBrowserPhase334Tests(Phase334TestCase):
    @unittest.skipUnless(chromium_available(), "Chromium executable required")
    def test_closed_alpha_first_commit_flow_publishes_custom_seo_and_status(self) -> None:
        repo = self.init_empty_site_repo()
        server, thread, base_url = self.live_dashboard()
        custom_seo = "Custom Chromium SEO description for phase 33.4."
        try:
            with self.static_server(repo) as site_port:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
                    try:
                        page = browser.new_page(viewport={"width": 390, "height": 844})
                        page.goto(base_url + "/health")
                        expect(page.get_by_text("phase33.4")).to_be_visible()
                        page.goto(base_url + "/setup")
                        page.get_by_label("Workspace name").fill("MVP Dogfood 334")
                        page.get_by_role("button", name="Start real setup").click()
                        session_id = page.url.rsplit("/", maxsplit=1)[-1]
                        for step in ("welcome", "host_preflight", "workspace", "operator_identity"):
                            page.goto(f"{base_url}/setup/{session_id}/{step}")
                            page.get_by_role("button", name="Save").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_destination")
                        page.get_by_label("Display name").fill("Dogfood Site 334")
                        page.get_by_label("Managed repository root").fill(str(repo.parent))
                        page.get_by_label("Repository", exact=True).fill(repo.name)
                        page.get_by_label("Branch").fill("main")
                        page.get_by_label("Public URL template").fill(
                            f"http://127.0.0.1:{site_port}/articles/{{slug}}.md"
                        )
                        page.get_by_role("button", name="Register destination").click()
                        page.goto(f"{base_url}/setup/{session_id}/website_account")
                        expect(page.get_by_text("No commits yet; first commit will be created").first).to_be_visible()
                        page.get_by_role("button", name="Save account").click()
                        page.goto(f"{base_url}/setup/{session_id}/first_content")
                        page.get_by_label("Title").fill("MVP Dogfood Publication 334")
                        page.get_by_label("Article body").fill(
                            "# MVP Dogfood Publication 334\n\nClosed alpha SEO proof."
                        )
                        page.get_by_text("SEO & settings").click()
                        page.get_by_label("Slug").fill("mvp-dogfood-publication-334")
                        page.get_by_label("SEO description").fill(custom_seo)
                        page.get_by_role("button", name="Create real draft and open composer").click()
                        draft_id = self.draft_id_from_composer_route(page.url)
                        page.get_by_text("SEO & settings").click()
                        expect(page.get_by_label("SEO description")).to_have_value(custom_seo)
                        page.get_by_label("Summary").fill("Fallback summary should not publish.")
                        expect(page.locator("#autosave-status")).to_contain_text("Saved", timeout=8000)
                        page.reload()
                        page.get_by_text("SEO & settings").click()
                        expect(page.get_by_label("SEO description")).to_have_value(custom_seo)
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)
                        server, thread, base_url = self.live_dashboard()
                        page.goto(f"{base_url}/content/{draft_id}/compose?setup_session={session_id}")
                        page.get_by_text("SEO & settings").click()
                        expect(page.get_by_label("SEO description")).to_have_value(custom_seo)
                        page.goto(f"{base_url}/setup/{session_id}/publication_plan")
                        page.get_by_role("button", name="Create real publication plan").click()
                        expect(page.get_by_text(custom_seo).first).to_be_visible()
                        page.goto(f"{base_url}/setup/{session_id}/review")
                        expect(page.get_by_text(custom_seo).first).to_be_visible()
                        page.get_by_label("Exact confirmation").fill(mvp_dashboard.CONFIRMATION_TEXT)
                        page.get_by_role("button", name="Publish").click()
                        expect(page.get_by_text("Publishing started")).to_be_visible(timeout=10000)
                        page.goto(f"{base_url}/setup/{session_id}/result")
                        expect(page.get_by_role("heading", name="Execution status")).to_be_visible()
                        expect(page.locator(".status-card").get_by_text("Completed", exact=True)).to_be_visible()
                        expect(page.get_by_text("Published").first).to_be_visible()
                        page.reload()
                        expect(page.locator(".status-card").get_by_text("Completed", exact=True)).to_be_visible()
                        markdown = (repo / "articles" / "mvp-dogfood-publication-334.md").read_text(encoding="utf-8")
                        self.assertIn(f'description: "{custom_seo}"', markdown)
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
