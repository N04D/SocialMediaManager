"""Browser automation for deterministic staging certification fixtures."""

from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from integrations.staging_analytics.fake_staging_site import synthetic_staging_page
from src.core.staging_analytics.errors import StagingAnalyticsError
from src.core.staging_analytics.models import StagingBrowserRequestEvidence, stable_checksum, utc_now_iso
from src.core.website_instrumentation.contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION


class StagingBrowserCertificationRunner:
    def __init__(self, *, chromium_executable: str | None = None) -> None:
        self.chromium_executable = chromium_executable

    def run(
        self, *, run_id: str, origin_reference: Any, page_profile: Any, browser_config: dict[str, Any]
    ) -> dict[str, Any]:
        from playwright.sync_api import sync_playwright

        executable = self.chromium_executable or _chromium_executable()
        page_url = origin_reference.page_url(page_profile.page_path)
        html = synthetic_staging_page(browser_config)
        evidence: list[StagingBrowserRequestEvidence] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            context = browser.new_context()
            page = context.new_page()
            page.route(page_url, lambda route: route.fulfill(status=200, body=html, content_type="text/html"))
            page.goto(page_url, wait_until="domcontentloaded")
            if page.locator('meta[name="smm-synthetic-analytics-page"][content="true"]').count() != 1:
                raise StagingAnalyticsError("staging_analytics.synthetic_marker", "Synthetic marker is missing.")
            robots = page.locator('meta[name="robots"]').get_attribute("content") or ""
            if "noindex" not in robots or "nofollow" not in robots:
                raise StagingAnalyticsError("staging_analytics.noindex", "Synthetic page must be noindex,nofollow.")
            version = page.locator('meta[name="smm-instrumentation-version"]').get_attribute("content") or ""
            if version != WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION:
                raise StagingAnalyticsError(
                    "staging_analytics.instrumentation_version", "Instrumentation version mismatch."
                )
            page.add_script_tag(path=str(Path("web/instrumentation/plausible-bridge.js").resolve()))
            page.add_script_tag(path=str(Path("web/instrumentation/smm-analytics.js").resolve()))
            page.evaluate(
                """cfg => {
                    window.__stagingEvents = [];
                    window.plausible = (name, options) => window.__stagingEvents.push({name, props: options.props, browserOrigin: true});
                    window.SMMAnalytics.initialize(cfg);
                    document.querySelectorAll("[data-smm-track]").forEach((node) => node.addEventListener("click", (event) => event.preventDefault()));
                }""",
                browser_config,
            )
            page.click("[data-smm-track='cta']")
            if page.evaluate("window.__stagingEvents.length") != 0:
                raise StagingAnalyticsError("staging_analytics.consent", "Event fired before consent.")
            page.evaluate("window.SMMAnalytics.setConsent(true)")
            page.click("[data-smm-track='cta']")
            page.click("[data-smm-track='conversion']")
            page.evaluate("window.SMMAnalytics.setConsent(false)")
            page.click("[data-smm-track='conversion']")
            events = list(page.evaluate("window.__stagingEvents"))
            if len(events) != 2:
                raise StagingAnalyticsError(
                    "staging_analytics.browser_events", "Expected exactly two synthetic events."
                )
            if context.cookies():
                raise StagingAnalyticsError("staging_analytics.cookies", "Browser context stored cookies.")
            if page.evaluate("localStorage.length + sessionStorage.length") != 0:
                raise StagingAnalyticsError("staging_analytics.storage", "Browser storage is not allowed.")
            browser.close()
        for item in events:
            props = dict(item.get("props", {}))
            names = tuple(sorted(props))
            checksum = stable_checksum({"run_id": run_id, "event": item.get("name"), "names": names})
            evidence.append(
                StagingBrowserRequestEvidence(
                    id="stg-browser-" + checksum[:16],
                    run_id=run_id,
                    event_type="synthetic_conversion"
                    if item.get("name") == "SMM Conversion"
                    else "synthetic_cta_click",
                    event_name=str(item.get("name")),
                    destination_origin_reference=origin_reference.id,
                    method="BROWSER_CONTEXT",
                    safe_property_names=names,
                    safe_property_fingerprint=stable_checksum(names),
                    instrumentation_version=WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
                    occurred_at=utc_now_iso(),
                    accepted_by_browser_runtime=bool(item.get("browserOrigin")),
                    checksum=checksum,
                )
            )
        return {
            "events": events,
            "evidence": evidence,
            "browser_version": _browser_version(executable),
            "consent_verified": True,
            "synthetic_marker_verified": True,
            "noindex_verified": True,
            "evidence_payload": [asdict(item) for item in evidence],
        }


def _chromium_executable() -> str:
    for candidate in (
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        "/snap/bin/chromium",
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise StagingAnalyticsError("staging_analytics.browser_missing", "Chromium executable is not available.")


def _browser_version(executable: str) -> str:
    return Path(executable).name or "chromium"


__all__ = ["StagingBrowserCertificationRunner"]
