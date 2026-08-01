from __future__ import annotations

import unittest

from playwright.sync_api import expect, sync_playwright

import mvp_dashboard
from tests.owned_publication_browser_certification import chromium_executable
from tests.phase331_support import chromium_available
from tests.phase333_support import Phase333TestCase


class MVPRealBrowserPhase333Tests(Phase333TestCase):
    @unittest.skipUnless(chromium_available(), "Chromium executable required")
    def test_empty_repo_real_chromium_flow_truthful_timeline_and_result(self) -> None:
        repo = self.init_empty_site_repo()
        server, thread, base_url = self.live_dashboard()
        try:
            with self.static_server(repo) as site_port:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
                    try:
                        page = browser.new_page(viewport={"width": 390, "height": 844})
                        page.goto(base_url + "/setup")
                        page.get_by_label("Workspace name").fill("MVP Dogfood 333")
                        page.get_by_role("button", name="Start real setup").click()
                        session_id = page.url.rsplit("/", maxsplit=1)[-1]
                        for step in ("welcome", "host_preflight", "workspace", "operator_identity"):
                            page.goto(f"{base_url}/setup/{session_id}/{step}")
                            page.get_by_role("button", name="Save").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_destination")
                        page.get_by_label("Display name").fill("Dogfood Site 333")
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
                        page.get_by_label("Title").fill("MVP Dogfood Publication 333")
                        page.get_by_label("Article body").fill("# MVP Dogfood Publication 333\n\nFirst commit proof.")
                        page.get_by_text("SEO & settings").click()
                        page.get_by_label("Slug").fill("mvp-dogfood-publication-333")
                        page.get_by_role("button", name="Create real draft and open composer").click()
                        expect(page.get_by_role("heading", name="Compose", exact=True)).to_be_visible()
                        draft_id = self.draft_id_from_composer_route(page.url)
                        page.get_by_label("Title").fill("MVP Dogfood Publication 333 Saved")
                        expect(page.locator("#autosave-status")).to_contain_text("Saved", timeout=8000)
                        first_version = int(page.locator("#owned-composer-form").get_attribute("data-version"))
                        stale_status, stale_payload = self.api_patch_content(
                            base_url,
                            draft_id,
                            {
                                "draft_id": draft_id,
                                "expected_version": first_version - 1,
                                "title": "stale",
                                "idempotency_key": "phase333-browser-stale",
                            },
                        )
                        self.assertEqual(stale_status, 409, stale_payload)
                        self.assertIn("current_server_version", stale_payload["error"])
                        page.get_by_role("link", name="Continue to publication plan").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_plan")
                        if page.get_by_role("button", name="Create real publication plan").count():
                            page.get_by_role("button", name="Create real publication plan").click()
                        page.get_by_text("Technical details").click()
                        expect(page.get_by_text("Revision checksum")).to_be_visible()
                        page.goto(f"{base_url}/setup/{session_id}/review")
                        page.get_by_label("Exact confirmation").fill(mvp_dashboard.CONFIRMATION_TEXT)
                        page.get_by_role("button", name="Publish").click()
                        page.get_by_text("Technical details").click()
                        expect(page.get_by_text("execution-")).to_be_visible(timeout=10000)
                        expect(page.get_by_text("Website saved")).to_be_visible(timeout=10000)
                        page.goto(f"{base_url}/setup/{session_id}/result")
                        page.get_by_text("Technical details").click()
                        expect(page.get_by_text("Execution ID")).to_be_visible()
                        expect(page.get_by_text("Published").first).to_be_visible()
                        expect(page.get_by_text("git-evidence-")).to_be_visible()
                        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-333.md").exists())
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
