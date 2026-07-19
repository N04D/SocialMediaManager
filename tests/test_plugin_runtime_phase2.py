from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channel_store import begin_channel_connect, get_channel_connection, list_channel_job_logs
from channels.linkedin.worker import connect as connect_module
from plugin_runtime import ApplicationPluginRuntime, bootstrap_plugins
from plugins.providers.legacy_browser import LegacyBrowserProvider
from src.core.browser import BrowserProfileBusyError, FileBackedBrowserProfileLockManager
from src.core.plugins import PluginCapabilityError, PluginDependencyError, PluginRegistry
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_support import isolated_channel_store


class Config:
    linkedin_user_data_dir = Path("/tmp/linkedin-profile")
    linkedin_feed_url = "https://www.linkedin.com/feed/"
    linkedin_wait_after_open_seconds = 0.1
    linkedin_remote_debugging_url = "http://127.0.0.1:9222"
    headless = False


class FakeLocator:
    def __init__(self, count_value: int) -> None:
        self._count_value = count_value

    def count(self) -> int:
        return self._count_value


class FakePage:
    def __init__(self, *, authenticated: bool = True, auto_auth_after_waits: int = -1) -> None:
        self.url = "about:blank"
        self.authenticated = authenticated
        self.auto_auth_after_waits = auto_auth_after_waits
        self.wait_calls = 0
        self.goto_count = 0
        self._handlers = {}
        self._main_frame = object()

    @property
    def main_frame(self):
        return self._main_frame

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def _emit(self) -> None:
        for handler in self._handlers.get("framenavigated", []):
            handler(self._main_frame)

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.goto_count += 1
        self.url = url if self.authenticated else "https://www.linkedin.com/login"
        self._emit()

    def wait_for_timeout(self, millis: int) -> None:
        self.wait_calls += 1
        if not self.authenticated and self.auto_auth_after_waits >= 0 and self.wait_calls >= self.auto_auth_after_waits:
            self.authenticated = True
            self.url = "https://www.linkedin.com/feed/"
            self._emit()

    def get_by_role(self, role: str, name=None):
        return FakeLocator(1 if self.authenticated and role == "button" else 0)

    def locator(self, selector: str):
        return FakeLocator(1 if self.authenticated and selector == "nav.global-nav" else 0)

    def title(self) -> str:
        return "LinkedIn"


class FakeContext:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def provider_manifest(plugin_id="provider.browser.legacy", status="ready"):
    return PluginManifest.from_dict(
        {
            "id": plugin_id,
            "name": plugin_id,
            "version": "0.1.0",
            "plugin_api_version": 1,
            "type": "provider",
            "entrypoint": "test",
            "status": status,
            "capabilities": [
                "browser.session",
                "browser.auth_profile",
                "browser.navigation",
                "browser.interaction",
                "browser.human_takeover",
            ],
            "dependencies": [],
            "config_schema": {},
        }
    )


def linkedin_manifest():
    return PluginManifest.from_dict(
        {
            "id": "channel.linkedin",
            "name": "LinkedIn",
            "version": "0.1.0",
            "plugin_api_version": 1,
            "type": "channel",
            "entrypoint": "channels.linkedin",
            "status": "ready",
            "capabilities": ["channel.connect"],
            "dependencies": [{"capability": "browser.session"}, {"capability": "browser.human_takeover"}],
            "config_schema": {},
        }
    )


def runtime_with_provider(provider) -> ApplicationPluginRuntime:
    manifest = provider_manifest()
    runtime = ApplicationPluginRuntime()
    runtime.registry.register(manifest)
    runtime.runtimes[manifest.id] = PluginRuntime(
        manifest=manifest, instance=provider, status=PluginStatus.READY, services={"browser_provider": provider}
    )
    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    return runtime


class RuntimeBootstrapTests(unittest.TestCase):
    def test_bootstrap_registers_legacy_provider_and_linkedin(self) -> None:
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            runtime = bootstrap_plugins(config, strict=False)
        self.assertIn("provider.browser.legacy", runtime.runtimes)
        self.assertIn("channel.linkedin", runtime.runtimes)

    def test_linkedin_dependencies_resolve(self) -> None:
        registry = PluginRegistry()
        registry.register(provider_manifest())
        channel = registry.register(linkedin_manifest())
        registry.validate_dependencies(channel)

    def test_missing_browser_provider_blocks_linkedin(self) -> None:
        registry = PluginRegistry()
        channel = registry.register(linkedin_manifest())
        with self.assertRaises(PluginDependencyError):
            registry.validate_dependencies(channel)

    def test_error_provider_is_not_selected(self) -> None:
        runtime = ApplicationPluginRuntime()
        manifest = provider_manifest(status="ready")
        runtime.registry.register(manifest)
        runtime.runtimes[manifest.id] = PluginRuntime(manifest=manifest, status=PluginStatus.ERROR)
        runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
        with self.assertRaises(PluginCapabilityError):
            runtime.resolve_provider("browser.session")

    def test_deterministic_provider_selection(self) -> None:
        runtime = ApplicationPluginRuntime()
        for plugin_id in ["provider.browser.z", "provider.browser.a"]:
            manifest = provider_manifest(plugin_id=plugin_id)
            runtime.registry.register(manifest)
            runtime.runtimes[plugin_id] = PluginRuntime(
                manifest=manifest, status=PluginStatus.READY, services={"browser_provider": object()}
            )
        runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
        self.assertEqual(runtime.resolve_provider("browser.session").manifest.id, "provider.browser.a")

    def test_runtime_service_belongs_to_manifest(self) -> None:
        provider = object()
        runtime = ApplicationPluginRuntime()
        manifest = provider_manifest()
        runtime.registry.register(manifest)
        runtime.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest, status=PluginStatus.READY, services={"browser_provider": provider}
        )
        runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
        self.assertIs(runtime.browser_provider(), provider)


class ConnectFlowProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir(parents=True)

    def _provider_for_page(self, page: FakePage, *, fail_open: bool = False):
        self.context = FakeContext()
        self.playwright = FakePlaywright()

        def open_session(*args, **kwargs):
            if fail_open:
                raise RuntimeError("remote browser unavailable")
            return self.playwright, None, self.context, page, True, "persistent profile"

        return LegacyBrowserProvider(config=self.config, open_session=open_session)

    def _begin(self):
        connection, _ = begin_channel_connect(
            "linkedin", mode="playwright_local", local_profile_path=str(self.config.linkedin_user_data_dir)
        )
        return connection

    def test_connect_with_existing_logged_in_profile(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(authenticated=True))
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            result = connect_module.run_connect_action(
                self.config, action_id=connection.active_job_id, worker_id="worker-a"
            )
        self.assertEqual(result.status, "connected")
        self.assertTrue(self.context.closed)
        self.assertFalse(provider.profile_status("linkedin").busy)

    def test_connect_authentication_required_creates_takeover_and_resumes(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(authenticated=False, auto_auth_after_waits=1))
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            result = connect_module.run_connect_action(
                self.config, action_id=connection.active_job_id, worker_id="worker-a"
            )
        self.assertEqual(result.status, "connected")
        self.assertEqual(result.last_connect_diagnostics_json["human_takeover_status"], "completed")

    def test_takeover_expires(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(authenticated=False))
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            with patch.object(connect_module, "wait_for_manual_linkedin_login", return_value=(False, "Timed out.")):
                result = connect_module.run_connect_action(
                    self.config, action_id=connection.active_job_id, worker_id="worker-a"
                )
        self.assertEqual(result.status, "needs_login")
        self.assertEqual(result.last_connect_diagnostics_json["human_takeover_status"], "expired")

    def test_browserprovider_unavailable_safe_message_reaches_ui(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(), fail_open=True)
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            result = connect_module.run_connect_action(
                self.config, action_id=connection.active_job_id, worker_id="worker-a"
            )
        self.assertEqual(result.status, "needs_login")
        self.assertEqual(result.last_error, "Could not open the configured browser session.")

    def test_profile_busy(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage())
        held = provider.lock_manager.acquire(
            "linkedin", owner="other", session_id="held", provider_id=provider.provider_id
        )
        self.addCleanup(held.release)
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            result = connect_module.run_connect_action(
                self.config, action_id=connection.active_job_id, worker_id="worker-a"
            )
        self.assertEqual(result.status, "error")
        self.assertIn("Browser profile is already in use", result.last_error)

    def test_lock_and_session_released_after_error(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(authenticated=True))
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            with patch.object(
                connect_module, "inspect_linkedin_auth_state", side_effect=RuntimeError("inspect failed")
            ):
                with self.assertRaises(RuntimeError):
                    connect_module.run_connect_action(
                        self.config, action_id=connection.active_job_id, worker_id="worker-a"
                    )
        self.assertFalse(provider.profile_status("linkedin").busy)
        self.assertTrue(self.context.closed)

    def test_linkedin_status_and_safe_log_are_stored(self) -> None:
        connection = self._begin()
        provider = self._provider_for_page(FakePage(authenticated=False))
        with patch.object(connect_module, "get_plugin_runtime", return_value=runtime_with_provider(provider)):
            with patch.object(connect_module, "wait_for_manual_linkedin_login", return_value=(False, "Please log in.")):
                connect_module.run_connect_action(self.config, action_id=connection.active_job_id, worker_id="worker-a")
        stored = get_channel_connection("linkedin")
        self.assertEqual(stored.status, "needs_login")
        self.assertEqual(stored.last_error, "Please log in.")
        self.assertTrue(
            any(log.error_code == "authentication_required" for log in list_channel_job_logs(channel_id="linkedin"))
        )


class FileBackedLockTests(unittest.TestCase):
    def test_exclusive_lock_same_process_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = FileBackedBrowserProfileLockManager(Path(tmp), lease_seconds=10)
            lock = manager.acquire("linkedin", owner="a", session_id="s1", provider_id="p")
            with self.assertRaises(BrowserProfileBusyError):
                manager.acquire("linkedin", owner="b", session_id="s2", provider_id="p")
            lock.release()
            self.assertFalse(manager.status("linkedin")["busy"])

    def test_exclusive_between_managers_active_not_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = FileBackedBrowserProfileLockManager(Path(tmp), lease_seconds=10)
            second = FileBackedBrowserProfileLockManager(Path(tmp), lease_seconds=10)
            lock = first.acquire("linkedin", owner="a", session_id="s1", provider_id="p")
            self.addCleanup(lock.release)
            with self.assertRaises(BrowserProfileBusyError):
                second.acquire("linkedin", owner="b", session_id="s2", provider_id="p")

    def test_expired_lease_heartbeat_release_wrong_owner_and_force_audit(self) -> None:
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            manager = FileBackedBrowserProfileLockManager(Path(tmp), lease_seconds=5, clock=lambda: now[0])
            lock = manager.acquire("linkedin", owner="a", session_id="s1", provider_id="p")
            now[0] = 1003.0
            lock.heartbeat()
            self.assertTrue(manager.status("linkedin")["busy"])
            now[0] = 1009.0
            self.assertTrue(manager.status("linkedin")["stale"])
            manager.release("linkedin", "wrong")
            self.assertTrue(manager.status("linkedin")["stale"])
            audit = manager.force_unlock("linkedin", admin_reason="manual confirmation")
            self.assertEqual(audit["old_owner"], "a")
            self.assertFalse(manager.status("linkedin")["busy"])
            self.assertTrue((Path(tmp) / "browser_profile_force_unlock_audit.jsonl").exists())

    def test_legacy_empty_lock_is_recognized_as_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = FileBackedBrowserProfileLockManager(Path(tmp), lease_seconds=5)
            manager.lock_path("linkedin").write_text("", encoding="utf-8")
            self.assertTrue(manager.status("linkedin")["stale"])


class HealthAndImportRegressionTests(unittest.TestCase):
    def test_healthy_legacy_provider_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config()
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            provider = LegacyBrowserProvider(config=config)
            self.assertIn(provider.health_check()["status"], {"ready", "degraded"})

    def test_missing_browser_dependency_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config()
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            provider = LegacyBrowserProvider(config=config)
            real_import = __import__

            def fake_import(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    raise ImportError("missing")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                self.assertEqual(provider.health_check()["status"], "degraded")

    def test_unwritable_profile_directory_reported(self) -> None:
        config = Config()
        provider = LegacyBrowserProvider(config=config)
        with patch("os.access", return_value=False):
            self.assertEqual(provider.health_check()["status"], "degraded")

    def test_linkedin_without_dependency_not_ready(self) -> None:
        registry = PluginRegistry()
        channel = registry.register(linkedin_manifest())
        with self.assertRaises(PluginDependencyError):
            registry.validate_dependencies(channel)

    def test_publish_metrics_and_scraping_imports_still_work(self) -> None:
        for module_name in ["pipeline", "bs4", "bs4.element"]:
            sys.modules.pop(module_name, None)
        import channels.linkedin.worker.metrics  # noqa: F401
        import channels.linkedin.worker.publish  # noqa: F401
        import pipeline  # noqa: F401
