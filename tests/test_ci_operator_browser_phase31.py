from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import build_operator_stack, complete_promoted_flow


class CiOperatorBrowserPhase31Tests(unittest.TestCase):
    def test_operator_wizard_metadata_survives_browser_reload_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            complete_promoted_flow(stack)
            html = _wizard_html(stack["operator"].status())
            try:
                from playwright.sync_api import sync_playwright
            except Exception as exc:  # pragma: no cover - environment guard
                self.fail(f"Playwright is required for phase 31 browser certification: {exc}")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.set_content(html)
                self.assertIn("artifact_imported_verified", page.locator("#remote-status").inner_text())
                self.assertIn("5001", page.locator("#artifact-id").inner_text())
                self.assertNotIn("github-token-synthetic", page.content())
                self.assertNotIn("Authorization", page.content())
                page.reload()
                page.set_content(html)
                self.assertIn("promoted", page.locator("#promotion-status").inner_text())
                browser.close()


def _wizard_html(status: dict) -> str:
    flow = status["flows"][-1]
    readiness = status["readiness"]
    return f"""
    <!doctype html>
    <html>
      <body>
        <main id="wizard">
          <section id="remote-status">{readiness["remote_ci_status"]}</section>
          <section id="artifact-id">{flow["selected_artifact_id"]}</section>
          <section id="run-attempt">{flow["selected_run_attempt"]}</section>
          <section id="promotion-status">{flow["status"]}</section>
          <input type="password" autocomplete="off" value="" />
        </main>
      </body>
    </html>
    """


if __name__ == "__main__":
    unittest.main()
