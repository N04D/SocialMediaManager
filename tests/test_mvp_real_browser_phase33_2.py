from __future__ import annotations

import unittest

from playwright.sync_api import expect, sync_playwright

import mvp_dashboard
from tests.owned_publication_browser_certification import chromium_executable
from tests.phase331_support import chromium_available
from tests.phase332_support import Phase332TestCase


class MVPRealBrowserPhase332Tests(Phase332TestCase):
    @unittest.skipUnless(chromium_available(), "Chromium executable required")
    def test_real_chromium_canonical_draft_to_verified_publication(self) -> None:
        repo = self.init_site_repo()
        server, thread, base_url = self.live_dashboard()
        try:
            with self.static_server(repo) as site_port:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 800})
                        page.goto(base_url + "/setup")
                        page.get_by_label("Workspace name").fill("MVP Dogfood 332")
                        page.get_by_role("button", name="Start real setup").click()
                        session_id = page.url.rsplit("/", maxsplit=1)[-1]
                        for step in ("welcome", "host_preflight", "workspace", "operator_identity"):
                            page.goto(f"{base_url}/setup/{session_id}/{step}")
                            page.get_by_role("button", name="Save").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_destination")
                        page.get_by_label("Display name").fill("Dogfood Site 332")
                        page.get_by_label("Managed repository root").fill(str(repo.parent))
                        page.get_by_label("Repository", exact=True).fill(repo.name)
                        page.get_by_label("Branch").fill("main")
                        page.get_by_label("Public URL template").fill(
                            f"http://127.0.0.1:{site_port}/articles/{{slug}}.md"
                        )
                        page.get_by_role("button", name="Register destination").click()
                        page.goto(f"{base_url}/setup/{session_id}/website_account")
                        expect(page.get_by_text("Website connected")).to_be_visible()
                        page.get_by_role("button", name="Save account").click()
                        page.goto(f"{base_url}/setup/{session_id}/first_content")
                        page.get_by_label("Title").fill("MVP Dogfood Publication 332")
                        page.get_by_label("Article body").fill(
                            "# MVP Dogfood Publication 332\n\nCanonical draft identity."
                        )
                        page.get_by_text("SEO & settings").click()
                        page.get_by_label("Slug").fill("mvp-dogfood-publication-332")
                        page.get_by_role("button", name="Create real draft and open composer").click()
                        expect(page.get_by_role("heading", name="Compose", exact=True)).to_be_visible()
                        draft_id = self.draft_id_from_composer_route(page.url)

                        api_payload = self.api_get_content(base_url, draft_id)
                        self.assertEqual(api_payload["draft_id"], draft_id)
                        self.assertEqual(
                            str(api_payload["version"]),
                            page.locator("#owned-composer-form").get_attribute("data-version"),
                        )
                        self.assertNotEqual(api_payload["draft_id"], "content-owned-1")
                        expect(page.get_by_label("Slug")).to_have_value("mvp-dogfood-publication-332")

                        page.get_by_label("Title").fill("MVP Dogfood Publication 332 Saved")
                        expect(page.locator("#autosave-status")).to_contain_text("Saved", timeout=8000)
                        first_version = int(page.locator("#owned-composer-form").get_attribute("data-version"))
                        self.assertEqual(first_version, api_payload["version"] + 1)
                        page.get_by_label("Article editor").fill(
                            "# MVP Dogfood Publication 332 Saved\n\nBrowser autosave persisted."
                        )
                        expect(page.locator("#autosave-status")).to_contain_text("Saved", timeout=8000)
                        second_version = int(page.locator("#owned-composer-form").get_attribute("data-version"))
                        self.assertEqual(second_version, first_version + 1)
                        page.reload()
                        expect(page.get_by_label("Article editor")).to_contain_text("Browser autosave persisted")

                        ctx_b = browser.new_context(viewport={"width": 1280, "height": 800})
                        ctx_b.close()
                        stale_status, stale_payload = self.api_patch_content(
                            base_url,
                            draft_id,
                            {
                                "draft_id": draft_id,
                                "expected_version": first_version,
                                "title": "stale",
                                "idempotency_key": "phase332-browser-stale",
                            },
                        )
                        self.assertEqual(stale_status, 409, stale_payload)

                        page.get_by_role("link", name="Continue to publication plan").click()
                        page.goto(f"{base_url}/setup/{session_id}/review")
                        page.goto(f"{base_url}/setup/{session_id}/publication_plan")
                        page.get_by_text("Technical details").click()
                        expect(page.get_by_text("Publication plan ID")).to_be_visible()
                        page.goto(f"{base_url}/setup/{session_id}/review")
                        page.get_by_text("Technical details").click()
                        expect(page.get_by_text(draft_id, exact=True)).to_be_visible()
                        page.get_by_label("Exact confirmation").fill(mvp_dashboard.CONFIRMATION_TEXT)
                        page.get_by_role("button", name="Publish").click()
                        expect(page.get_by_text("Website saved")).to_be_visible(timeout=10000)
                        page.goto(f"{base_url}/setup/{session_id}/result")
                        expect(page.get_by_text("Published").first).to_be_visible()
                        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-332.md").exists())
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
