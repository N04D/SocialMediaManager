from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from plugins.providers.auto_browser import AutoBrowserConfig, AutoBrowserProvider
from src.core.browser import BrowserSessionOptions, BrowserTarget, FileBackedBrowserProfileLockManager


@unittest.skipUnless(os.environ.get("AUTO_BROWSER_INTEGRATION") == "1", "set AUTO_BROWSER_INTEGRATION=1")
class RealAutoBrowserIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture_url = os.environ.get("AUTO_BROWSER_FIXTURE_URL", "http://127.0.0.1:8765/")
        self.provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url=os.environ["AUTO_BROWSER_BASE_URL"],
                bearer_token=os.environ.get("AUTO_BROWSER_BEARER_TOKEN", ""),
                operator_id=os.environ.get("AUTO_BROWSER_OPERATOR_ID", "social-media-manager"),
                expected_server_version=os.environ.get("AUTO_BROWSER_EXPECTED_VERSION", "1.3.1"),
                shared_upload_host_dir=str(Path(self.tmp.name) / "uploads"),
            ),
            lock_manager=FileBackedBrowserProfileLockManager(Path(self.tmp.name) / "locks"),
            mapping_path=Path(self.tmp.name) / "sessions.json",
        )

    def test_real_controller_fixture_lifecycle_targets_artifacts_and_cleanup(self) -> None:
        health = self.provider.health_check()
        self.assertEqual(health["status"], "ready")
        session = self.provider.create_session(
            BrowserSessionOptions(
                profile_id="integration-linkedin-test",
                start_url=self.fixture_url,
                exclusive=True,
                metadata={"purpose": "auto_browser.integration", "job_id": "integration"},
            )
        )
        try:
            self.assertIn("8765", session.current_url())
            self.assertTrue(session.title())
            primary = BrowserTarget(role="button", accessible_name="Primary action")
            self.assertTrue(session.element_exists(primary))
            session.click(primary)
            message = BrowserTarget(label="Message")
            if session.element_exists(message):
                session.fill(message, "hello")
                session.clear(message)
            self.assertIsNotNone(session.screenshot())
            result = session.evaluate("() => ({ok: true, title: document.title})")
            self.assertIsNotNone(result)
            session.navigate(self.fixture_url.rstrip("/") + "/second")
            self.assertIn("/second", session.current_url())
            session.go_back()
        finally:
            session.close()
        self.assertFalse(self.provider.profile_status("integration-linkedin-test").busy)
