from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mvp_dashboard import CONFIRMATION_TEXT, MVP_DATABASE, alpha_ui_service, handle_mvp_post, render_mvp_page
from src.core.alpha_onboarding.service import AlphaOnboardingService


class Phase33UITestCase(unittest.TestCase):
    def make_service(self) -> AlphaOnboardingService:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return AlphaOnboardingService(database_path=Path(self.tmp.name) / "phase33.sqlite3")

    def complete_demo(self) -> dict[str, object]:
        if MVP_DATABASE.exists():
            MVP_DATABASE.unlink()
        service = alpha_ui_service()
        payload = service.demo_start()
        session_id = payload["session"]["id"]
        for step_id in (
            "publication_destination",
            "website_account",
            "analytics_account",
            "instrumentation",
            "social_channels",
            "first_content",
            "publication_plan",
            "final_review",
        ):
            payload = service.complete_step(
                session_id, step_id, {"expected_version": service.get(session_id)["session"]["version"]}
            )
        review = service.publication_review(session_id)
        publish = service.publication_confirm(
            session_id,
            {
                "confirmation": CONFIRMATION_TEXT,
                "expected_version": service.get(session_id)["session"]["version"],
            },
        )
        payload = service.complete_step(
            session_id, "publish", {"expected_version": service.get(session_id)["session"]["version"]}
        )
        payload = service.complete_step(
            session_id, "verification", {"expected_version": service.get(session_id)["session"]["version"]}
        )
        sync = service.analytics_sync(session_id)
        payload = service.complete_step(
            session_id, "analytics_sync", {"expected_version": service.get(session_id)["session"]["version"]}
        )
        funnel = service.funnel(session_id)
        payload = service.complete_step(
            session_id, "first_funnel", {"expected_version": service.get(session_id)["session"]["version"]}
        )
        payload = service.complete_step(
            session_id, "completion", {"expected_version": service.get(session_id)["session"]["version"]}
        )
        return {"payload": payload, "review": review, "publish": publish, "sync": sync, "funnel": funnel}

    def assert_html_contains(self, path: str, *needles: str) -> str:
        html, status = render_mvp_page(path)
        self.assertEqual(status.value, 200)
        for needle in needles:
            self.assertIn(needle, html)
        return html

    def assert_no_sensitive_fixture_data(self, value: str) -> None:
        lowered = value.lower()
        forbidden = (
            "bearer ",
            "private key",
            "raw token",
            "linkedin-channel-dry-run",
            "soera-al-fathia",
            "content/drafts",
            "drafts/",
            "localstorage",
            "sessionstorage",
            "production_ready=true",
        )
        for item in forbidden:
            self.assertNotIn(item, lowered)

    def start_demo_via_ui(self) -> str:
        if MVP_DATABASE.exists():
            MVP_DATABASE.unlink()
        payload, status = handle_mvp_post("/setup/start-demo", {})
        self.assertEqual(status.value, 303)
        self.assertIn("alpha-session-", payload)
        return payload.split("/setup/", 1)[1].split('"', 1)[0]


def confirmation_text() -> str:
    return CONFIRMATION_TEXT
