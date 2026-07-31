from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

import dashboard
from tests.owned_publication_browser_certification import chromium_executable
from tests.phase331_support import Phase331TestCase, chromium_available


class MVPRealBrowserPhase331Tests(Phase331TestCase):
    @unittest.skipUnless(chromium_available(), "Chromium executable required")
    def test_real_chromium_wizard_publishes_markdown_website(self) -> None:
        repo = self.init_site_repo()
        (self.root / "config.json").write_text(
            json.dumps({"content_dir": str(self.root / "content")}), encoding="utf-8"
        )
        handler = type("Phase331BrowserHandler", (dashboard.DashboardHandler,), {})
        handler.config_path = str(self.root / "config.json")
        handler.config = SimpleNamespace(content_dir=self.root / "content", rss_url="https://example.invalid/feed")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.static_server(repo) as site_port:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 800})
                        page.goto(base_url + "/setup")
                        page.get_by_label("Workspace name").fill("MVP Dogfood 001")
                        page.get_by_role("button", name="Start real setup").click()
                        expect(page.get_by_role("heading", name="Setup", exact=True)).to_be_visible()
                        session_id = page.url.rsplit("/", maxsplit=1)[-1]
                        self.assertNotIn("Demo environment", page.content())
                        for step in ("welcome", "host_preflight", "workspace", "operator_identity"):
                            page.goto(f"{base_url}/setup/{session_id}/{step}")
                            page.get_by_role("button", name="Save").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_destination")
                        page.get_by_label("Display name").fill("Dogfood Site")
                        page.get_by_label("Managed repository root").fill(str(repo.parent))
                        page.get_by_label("Repository", exact=True).fill(repo.name)
                        page.get_by_label("Branch").fill("main")
                        page.get_by_label("Public URL template").fill(
                            f"http://127.0.0.1:{site_port}/articles/{{slug}}.md"
                        )
                        page.get_by_role("button", name="Register destination").click()
                        page.goto(f"{base_url}/setup/{session_id}/website_account")
                        expect(page.get_by_text("Repository registered")).to_be_visible()
                        expect(page.get_by_text("PASS").first).to_be_visible()
                        page.get_by_role("button", name="Save account").click()
                        page.goto(f"{base_url}/setup/{session_id}/first_content")
                        page.get_by_role("button", name="Create real draft and open composer").click()
                        expect(page.get_by_role("heading", name="Compose", exact=True)).to_be_visible()
                        expect(page.get_by_text("Autosave: saved")).to_be_visible(timeout=5000)
                        page.get_by_role("link", name="Continue to publication plan").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_plan")
                        page.get_by_role("button", name="Create real publication plan").click()
                        page.goto(f"{base_url}/setup/{session_id}/publication_plan")
                        expect(page.get_by_text("Publication plan ID")).to_be_visible()
                        page.goto(f"{base_url}/setup/{session_id}/review")
                        page.get_by_label("Exact confirmation").fill("Publish this immutable revision using this plan")
                        page.get_by_role("button", name="Publish").click()
                        expect(page.get_by_text("Git commit created")).to_be_visible(timeout=10000)
                        page.goto(f"{base_url}/setup/{session_id}/result")
                        expect(page.get_by_text("publication_verified")).to_be_visible()
                        self.assertTrue((repo / "articles" / "mvp-dogfood-publication-001.md").exists())
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
