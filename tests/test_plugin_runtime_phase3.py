from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channels.linkedin.runtime import LinkedInChannelRuntime, LinkedInChannelRuntimeError
from plugin_runtime import bootstrap_plugins
from plugins.providers.legacy_browser import LegacyBrowserProvider
from src.core.browser import (
    BrowserProfileBusyError,
    BrowserSessionOptions,
    FileBackedBrowserProfileLockManager,
)
from src.core.plugins import PluginCapabilityError
from src.core.plugins.manifest import PluginStatus
from tests.test_plugin_runtime_phase2 import Config, FakeContext, FakePage, FakePlaywright, runtime_with_provider
from tests.test_support import isolated_channel_store


class RecordingProvider:
    provider_id = "provider.browser.recording"

    def __init__(self) -> None:
        self.sessions = []
        self.takeovers = []
        self.lock_manager = FileBackedBrowserProfileLockManager(Path(tempfile.mkdtemp()))

    def create_session(self, options: BrowserSessionOptions):
        self.sessions.append(options)
        from src.core.browser.fake_provider import InMemoryBrowserProvider

        provider = InMemoryBrowserProvider(lock_manager=self.lock_manager)
        provider.element_exists_result = True
        return provider.create_session(options)

    def profile_status(self, profile_id: str):
        from src.core.browser import BrowserProfileStatus

        return BrowserProfileStatus(profile_id=profile_id, available=True)

    def health_check(self):
        return {"status": "ready"}

    def request_human_takeover(self, request):
        self.takeovers.append(request)
        return {"status": "requested", "takeover_reference": "takeover:test"}


class Phase3RuntimeServiceTests(unittest.TestCase):
    def test_runtime_service_registered_for_linkedin(self) -> None:
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            runtime = bootstrap_plugins(config, strict=False)
        service = runtime.get_plugin_service("channel.linkedin", "channel_runtime")
        self.assertIsInstance(service, LinkedInChannelRuntime)
        self.assertEqual(service.manifest.id, "channel.linkedin")

    def test_dashboard_and_worker_use_same_service_definition(self) -> None:
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            runtime = bootstrap_plugins(config, strict=False)
            import sys

            sys.modules.pop("pipeline", None)
            import worker

            with patch.object(worker, "get_plugin_runtime", return_value=runtime):
                service = worker._channel_runtime_service(config, "linkedin")
        self.assertEqual(service.service_name, "channel_runtime")

    def test_disabled_linkedin_plugin_has_no_operation_service(self) -> None:
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            runtime = bootstrap_plugins(config, strict=False)
        runtime.runtimes["channel.linkedin"].status = PluginStatus.DISABLED
        with self.assertRaises(PluginCapabilityError):
            runtime.get_plugin_service("channel.linkedin", "channel_runtime")

    def test_explicit_invalid_provider_fails_without_fallback(self) -> None:
        config = Config()
        config.linkedin_browser_provider_id = "provider.browser.missing"
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            runtime = bootstrap_plugins(config, strict=False)
        service = runtime.get_plugin_service("channel.linkedin", "channel_runtime")
        with self.assertRaises(LinkedInChannelRuntimeError):
            service.browser_provider()


class Phase3SessionCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir(parents=True)

    def _legacy_provider(self, page: FakePage):
        self.context = FakeContext()
        self.playwright = FakePlaywright()

        def open_session(*args, **kwargs):
            return self.playwright, None, self.context, page, True, "persistent profile"

        return LegacyBrowserProvider(config=self.config, open_session=open_session)

    def test_session_check_uses_provider_without_human_takeover(self) -> None:
        provider = self._legacy_provider(FakePage(authenticated=True))
        runtime = runtime_with_provider(provider)
        from channels.linkedin.worker.session import run_session_check_with_runtime

        result = run_session_check_with_runtime(self.config, runtime, worker_id="worker-a")
        self.assertEqual(result.status, "connected")
        self.assertFalse(provider.profile_status("linkedin").busy)
        self.assertTrue(self.context.closed)
        self.assertEqual(result.last_connect_diagnostics_json["human_takeover_status"], "not_required")

    def test_session_check_authentication_required(self) -> None:
        provider = self._legacy_provider(FakePage(authenticated=False))
        runtime = runtime_with_provider(provider)
        from channels.linkedin.worker.session import run_session_check_with_runtime

        result = run_session_check_with_runtime(self.config, runtime, worker_id="worker-a")
        self.assertEqual(result.status, "needs_login")
        self.assertEqual(provider.sessions, {})


class Phase3LockAndBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir(parents=True)

    def test_connect_and_publish_share_provider_lock(self) -> None:
        provider = LegacyBrowserProvider(
            config=self.config,
            open_session=lambda *a, **k: (FakePlaywright(), None, FakeContext(), FakePage(), True, "profile"),
        )
        held = provider.lock_manager.acquire(
            "linkedin", owner="connect", session_id="s1", provider_id=provider.provider_id
        )
        self.addCleanup(held.release)
        with self.assertRaises(BrowserProfileBusyError):
            provider.create_session(
                BrowserSessionOptions(
                    profile_id="linkedin",
                    exclusive=True,
                    metadata={"purpose": "linkedin.publish", "job_id": "publish-1"},
                )
            )

    def test_lock_metadata_contains_purpose_and_job_id(self) -> None:
        provider = LegacyBrowserProvider(
            config=self.config,
            open_session=lambda *a, **k: (FakePlaywright(), None, FakeContext(), FakePage(), True, "profile"),
        )
        session = None
        try:
            session = provider.create_session(
                BrowserSessionOptions(
                    profile_id="linkedin",
                    exclusive=True,
                    metadata={"purpose": "linkedin.metrics", "job_id": "metric-1"},
                )
            )
            raw = json.loads(provider.lock_manager.lock_path("linkedin").read_text(encoding="utf-8"))
            self.assertEqual(raw["purpose"], "linkedin.metrics")
            self.assertEqual(raw["job_id"], "metric-1")
        finally:
            if session is not None:
                session.close()
            self.assertFalse(provider.profile_status("linkedin").busy)

    def test_active_flows_do_not_call_old_lock_helper(self) -> None:
        import channels.linkedin.worker.browser as browser_module
        from channels.linkedin.worker.session import run_session_check_with_runtime

        provider = LegacyBrowserProvider(
            config=self.config,
            open_session=lambda *a, **k: (FakePlaywright(), None, FakeContext(), FakePage(), True, "profile"),
        )
        with patch.object(browser_module, "linkedin_profile_lock", side_effect=AssertionError("old lock used")):
            result = run_session_check_with_runtime(self.config, runtime_with_provider(provider), worker_id="worker-a")
        self.assertEqual(result.status, "connected")


class Phase3HealthAndForceUnlockTests(unittest.TestCase):
    def test_health_payload_contains_plugins_without_secret_paths(self) -> None:
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "secret-profile"
            runtime = bootstrap_plugins(config, strict=False)
        payload = runtime.health_payload()
        ids = {item["id"] for item in payload["plugins"]}
        self.assertIn("provider.browser.legacy", ids)
        self.assertIn("channel.linkedin", ids)
        self.assertNotIn("secret-profile", json.dumps(payload))

    def test_force_unlock_requires_reason_and_confirmation(self) -> None:
        import sys

        sys.modules.pop("pipeline", None)
        from dashboard import validate_force_unlock_confirmation

        ok, message = validate_force_unlock_confirmation("short", "yes")
        self.assertFalse(ok)
        self.assertIn("reason", message)
        ok, message = validate_force_unlock_confirmation("manual unlock reason", "")
        self.assertFalse(ok)
        self.assertIn("confirmation", message)
        ok, message = validate_force_unlock_confirmation("manual unlock reason", "yes")
        self.assertTrue(ok)
        self.assertEqual(message, "")

    def test_force_unlock_audit_contains_reason_owner_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = FileBackedBrowserProfileLockManager(Path(tmp))
            lock = manager.acquire(
                "linkedin", owner="owner-a", session_id="session-a", provider_id="provider.browser.legacy"
            )
            audit = manager.force_unlock("linkedin", admin_reason="manual confirmation", actor="tester")
            self.assertEqual(audit["old_owner"], "owner-a")
            self.assertEqual(audit["reason"], "manual confirmation")
            self.assertEqual(audit["result"], "lock_removed")
            lock.release()


class Phase3ImportIsolationTests(unittest.TestCase):
    def test_core_has_no_linkedin_playwright_or_autobrowser_imports(self) -> None:
        root = Path("src/core")
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
        self.assertNotIn("linkedin", text.lower())
        self.assertNotIn("playwright", text.lower())
        self.assertNotIn("autobrowser", text.lower())

    def test_linkedin_runtime_does_not_import_legacy_provider(self) -> None:
        text = Path("channels/linkedin/runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("LegacyBrowserProvider", text)

    def test_dashboard_and_worker_import(self) -> None:
        import sys

        for module_name in ["pipeline", "bs4", "bs4.element"]:
            sys.modules.pop(module_name, None)
        import dashboard as dashboard_module  # noqa: F401
        import worker as worker_module  # noqa: F401
