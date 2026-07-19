from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

pipeline_stub = types.ModuleType('pipeline')


class _AppConfig:
    linkedin_user_data_dir = Path('/tmp/linkedin-profile')
    linkedin_feed_url = 'https://www.linkedin.com/feed/'
    linkedin_wait_after_open_seconds = 0.1
    linkedin_remote_debugging_url = ''
    headless = False


pipeline_stub.AppConfig = _AppConfig
pipeline_stub.POST_BUTTON_PATTERNS = [r'post']
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
sys.modules.setdefault('pipeline', pipeline_stub)

from plugins.providers.legacy_browser import LegacyBrowserProvider
from channels.linkedin.worker import browser as linkedin_browser_module
from src.core.browser import (
    BrowserProfileBusyError,
    FileBackedBrowserProfileLockManager,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserTarget,
    HumanTakeoverRequest,
)
from src.core.browser.fake_provider import InMemoryBrowserProvider
from src.core.plugins import PluginDependency, PluginDependencyError, PluginRegistry, PluginValidationError
from src.core.plugins.manifest import PluginManifest, PluginType


def browser_manifest(**overrides):
    payload = {
        "id": "provider.browser.fake",
        "name": "Fake Browser Provider",
        "version": "0.1.0",
        "plugin_api_version": 1,
        "type": "provider",
        "entrypoint": "src.core.browser.fake_provider",
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
    payload.update(overrides)
    return payload


class PluginFrameworkTests(unittest.TestCase):
    def test_valid_plugin_manifest(self) -> None:
        manifest = PluginManifest.from_dict(browser_manifest())
        manifest.validate()
        self.assertEqual(manifest.id, "provider.browser.fake")
        self.assertEqual(manifest.type, PluginType.PROVIDER)

    def test_invalid_plugin_manifest(self) -> None:
        payload = browser_manifest()
        payload.pop("entrypoint")
        with self.assertRaises(PluginValidationError) as raised:
            PluginManifest.from_dict(payload)
        self.assertEqual(raised.exception.code, "plugin_manifest.invalid")

    def test_duplicate_plugin_id(self) -> None:
        registry = PluginRegistry()
        registry.register(browser_manifest())
        with self.assertRaises(PluginValidationError) as raised:
            registry.register(browser_manifest())
        self.assertEqual(raised.exception.code, "plugin_manifest.duplicate_id")

    def test_capability_registration(self) -> None:
        registry = PluginRegistry()
        registry.register(browser_manifest())
        providers = registry.providers_for("browser.session")
        self.assertEqual([provider.id for provider in providers], ["provider.browser.fake"])

    def test_missing_dependency(self) -> None:
        registry = PluginRegistry()
        channel = PluginManifest.from_dict(
            {
                "id": "channel.linkedin",
                "name": "LinkedIn",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "channel",
                "entrypoint": "channels.linkedin",
                "capabilities": [],
                "dependencies": [{"capability": "browser.session"}],
                "config_schema": {},
            }
        )
        registry.register(channel)
        with self.assertRaises(PluginDependencyError) as raised:
            registry.validate_dependencies(channel)
        self.assertEqual(raised.exception.details["missing"][0]["capability"], "browser.session")

    def test_incompatible_plugin_api_version(self) -> None:
        with self.assertRaises(PluginValidationError) as raised:
            PluginRegistry().register(browser_manifest(plugin_api_version=2))
        self.assertEqual(raised.exception.code, "plugin_manifest.incompatible_api_version")

    def test_dependency_capabilities_resolve_to_provider(self) -> None:
        registry = PluginRegistry()
        registry.register(browser_manifest())
        channel = PluginManifest.from_dict(
            {
                "id": "channel.linkedin",
                "name": "LinkedIn",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "channel",
                "entrypoint": "channels.linkedin",
                "capabilities": [],
                "dependencies": [
                    {"capability": "browser.session"},
                    {"capability": "browser.auth_profile"},
                    {"capability": "browser.human_takeover"},
                ],
                "config_schema": {},
            }
        )
        registry.register(channel)
        registry.validate_dependencies(channel)
        self.assertEqual(registry.require_provider_for("browser.human_takeover").id, "provider.browser.fake")


class BrowserProviderContractTests(unittest.TestCase):
    def test_successful_browser_session(self) -> None:
        provider = InMemoryBrowserProvider()
        session = provider.create_session(BrowserSessionOptions(profile_id="profile-a", start_url="https://example.test"))
        snapshot = session.navigate("https://example.test/feed")
        self.assertEqual(snapshot.url, "https://example.test/feed")
        self.assertIs(provider.get_session(session.session_id), session)

    def test_profile_locking(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.create_session(BrowserSessionOptions(profile_id="profile-a"))
        with self.assertRaises(BrowserProfileBusyError):
            provider.create_session(BrowserSessionOptions(profile_id="profile-a"))

    def test_lock_release_after_start_error(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.simulate_failure("create_session")
        with self.assertRaises(BrowserProviderError):
            provider.create_session(BrowserSessionOptions(profile_id="profile-a"))
        self.assertFalse(provider.profile_status("profile-a").busy)

    def test_provider_health_check(self) -> None:
        provider = InMemoryBrowserProvider()
        self.assertTrue(provider.health_check()["ok"])

    def test_human_takeover(self) -> None:
        provider = InMemoryBrowserProvider()
        session = provider.create_session(BrowserSessionOptions(profile_id="profile-a"))
        result = provider.request_human_takeover(HumanTakeoverRequest(session.session_id, "login"))
        self.assertEqual(result["status"], "requested")
        self.assertEqual(provider.takeovers[0].reason, "login")

    def test_fake_provider_records_screenshots_and_interactions(self) -> None:
        provider = InMemoryBrowserProvider()
        session = provider.create_session(BrowserSessionOptions(profile_id="profile-a"))
        session.click(BrowserTarget(role="button", accessible_name="Publish"))
        artifact = session.screenshot()
        self.assertEqual(artifact.kind, "screenshot")
        self.assertEqual(provider.actions[-1].action, "screenshot")


class LegacyBrowserProviderTests(unittest.TestCase):
    def test_legacy_browser_provider_adapter(self) -> None:
        class FakePage:
            url = "about:blank"

            def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
                self.url = url

            def title(self) -> str:
                return "Fake"

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

        context = FakeContext()
        playwright = FakePlaywright()

        def open_session(*args, **kwargs):
            return playwright, None, context, FakePage(), True, "persistent profile"

        with tempfile.TemporaryDirectory() as tmp:
            lock_manager = FileBackedBrowserProfileLockManager(Path(tmp))
            provider = LegacyBrowserProvider(config=object(), open_session=open_session, lock_manager=lock_manager)
            session = provider.create_session(BrowserSessionOptions(profile_id="linkedin", start_url="https://linkedin.test"))
            self.assertEqual(session.snapshot().url, "https://linkedin.test")
            session.close()
            self.assertTrue(context.closed)
            self.assertTrue(playwright.stopped)
            self.assertIsNone(provider.get_session(session.session_id))

    def test_legacy_provider_profile_status_uses_provider_lock_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_manager = FileBackedBrowserProfileLockManager(Path(tmp))
            provider = LegacyBrowserProvider(config=object(), lock_manager=lock_manager)
            self.assertTrue(provider.profile_status("linkedin").available)
