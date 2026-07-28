from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from integrations.website_instrumentation.scenarios import default_snapshot_payload, instrumentation_config_payload
from src.core.website_instrumentation.manifests import build_manifest
from src.core.website_instrumentation.renderer import render_static_page
from src.core.website_instrumentation.service import WebsiteInstrumentationService
from tests.owned_publication_browser_certification import chromium_executable


class WebsiteInstrumentationBrowserPhase26Tests(unittest.TestCase):
    def test_real_browser_consent_event_payload_and_no_storage(self) -> None:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            service = WebsiteInstrumentationService(database_path=Path(tmp) / "owned.sqlite3")
            config = service.create_config(instrumentation_config_payload())["config"]
            manifest = build_manifest(service.repository.get_config(config["id"]), default_snapshot_payload())
            html = render_static_page(manifest)
            runtime = str(Path("web/instrumentation/smm-analytics.js").resolve())
            bridge = str(Path("web/instrumentation/plausible-bridge.js").resolve())
            browser_config = {
                "consentMode": manifest.consent_mode,
                "pageContext": asdict(manifest.page_context),
                "events": list(manifest.expected_events),
            }
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable())
                page = browser.new_page()
                page.route(
                    "http://smm.test/**", lambda route: route.fulfill(status=200, body=html, content_type="text/html")
                )
                page.goto(
                    default_snapshot_payload()["public_url"].replace("https://example.com", "http://smm.test"),
                    wait_until="domcontentloaded",
                )
                page.add_script_tag(path=bridge)
                page.add_script_tag(path=runtime)
                page.evaluate(
                    """cfg => {
                        window.__events = [];
                        window.plausible = (name, options) => window.__events.push({name, props: options.props});
                        window.SMMAnalytics.initialize(cfg);
                    }""",
                    browser_config,
                )
                page.evaluate(
                    """() => document.querySelectorAll("[data-smm-track]").forEach((node) => node.addEventListener("click", (event) => event.preventDefault()))"""
                )
                page.click("[data-smm-track='cta']")
                self.assertEqual(page.evaluate("window.__events.length"), 0)
                page.evaluate("window.SMMAnalytics.setConsent(true)")
                page.click("[data-smm-track='cta']")
                events = page.evaluate("window.__events")
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["name"], "SMM CTA Click")
                self.assertEqual(events[0]["props"]["publication_id"], manifest.page_context.publication_id)
                self.assertNotIn("email", json.dumps(events))
                page.press("[data-smm-track='cta']", "Enter")
                self.assertEqual(page.evaluate("window.__events.length"), 1)
                page.click("[data-smm-track='conversion']")
                self.assertEqual(page.evaluate("window.__events[1].name"), "SMM Conversion")
                self.assertEqual(page.context.cookies(), [])
                self.assertEqual(page.evaluate("localStorage.length + sessionStorage.length"), 0)
                browser.close()


if __name__ == "__main__":
    unittest.main()
