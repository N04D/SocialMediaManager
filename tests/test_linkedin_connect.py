from __future__ import annotations

import fcntl
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_runtime import ApplicationPluginRuntime
from plugins.providers.legacy_browser import LegacyBrowserProvider
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver

pipeline_stub = types.ModuleType('pipeline')


class _AppConfig:
    linkedin_user_data_dir = Path('./linkedin_session')
    linkedin_feed_url = 'https://www.linkedin.com/feed/'
    linkedin_wait_after_open_seconds = 0.1
    linkedin_remote_debugging_url = ''
    headless = False


pipeline_stub.AppConfig = _AppConfig
pipeline_stub.POST_BUTTON_PATTERNS = [r'post']
pipeline_stub.run_local_ai = lambda *args, **kwargs: 'stubbed derivative'
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
sys.modules['pipeline'] = pipeline_stub

from channel_store import begin_channel_connect, claim_channel_connect, get_channel_connection
from channels.linkedin.worker import browser as browser_module
from channels.linkedin.worker import connect as connect_module
from channels.linkedin.worker import session as session_module
from tests.test_support import isolated_channel_store, install_pipeline_stub

install_pipeline_stub()


class FakeLocator:
    def __init__(self, count_value: int) -> None:
        self._count_value = count_value

    def count(self) -> int:
        return self._count_value


class FakePage:
    def __init__(self, *, login_url: str, feed_url: str, auto_auth_after_waits: int = -1) -> None:
        self.url = 'about:blank'
        self.login_url = login_url
        self.feed_url = feed_url
        self.auto_auth_after_waits = auto_auth_after_waits
        self.goto_count = 0
        self.reload_count = 0
        self.wait_calls = 0
        self.authenticated = False
        self._handlers: dict[str, list] = {}
        self._main_frame = object()

    @property
    def main_frame(self):
        return self._main_frame

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def _emit_main_frame_navigation(self) -> None:
        for handler in self._handlers.get('framenavigated', []):
            handler(self._main_frame)

    def goto(self, url: str, wait_until: str = 'domcontentloaded') -> None:
        self.goto_count += 1
        self.url = self.login_url if not self.authenticated else self.feed_url
        self._emit_main_frame_navigation()

    def reload(self) -> None:
        self.reload_count += 1
        self._emit_main_frame_navigation()

    def wait_for_timeout(self, millis: int) -> None:
        self.wait_calls += 1
        if not self.authenticated and self.auto_auth_after_waits >= 0 and self.wait_calls >= self.auto_auth_after_waits:
            self.authenticated = True
            self.url = self.feed_url
            self._emit_main_frame_navigation()

    def get_by_role(self, role: str, name=None):
        count_value = 1 if self.authenticated and role == 'button' else 0
        return FakeLocator(count_value)

    def locator(self, selector: str):
        count_value = 1 if self.authenticated and selector in {
            'nav.global-nav',
            "a[href*='/feed/']",
            "button[aria-label*='Start a post']",
            'div.share-box-feed-entry__top-bar',
        } else 0
        return FakeLocator(count_value)


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


def fake_plugin_runtime_for_session(config, open_session):
    provider_manifest = PluginManifest.from_dict({
        "id": "provider.browser.legacy",
        "name": "Legacy Browser Provider",
        "version": "0.1.0",
        "plugin_api_version": 1,
        "type": "provider",
        "entrypoint": "plugins.providers.legacy_browser.provider",
        "status": "ready",
        "capabilities": [
            "browser.session",
            "browser.auth_profile",
            "browser.navigation",
            "browser.interaction",
            "browser.human_takeover",
        ],
        "dependencies": [],
        "config_schema": {},
    })
    provider = LegacyBrowserProvider(config=config, open_session=open_session)
    runtime = ApplicationPluginRuntime()
    runtime.registry.register(provider_manifest)
    runtime.runtimes[provider_manifest.id] = PluginRuntime(
        manifest=provider_manifest,
        instance=provider,
        status=PluginStatus.READY,
        services={"browser_provider": provider},
    )
    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    return runtime


class LinkedInConnectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)
        self.config = _AppConfig()
        self.config.linkedin_user_data_dir = Path(self._tmp.name) / 'linkedin_session'
        self.config.linkedin_user_data_dir.mkdir(parents=True, exist_ok=True)
        self.config.linkedin_feed_url = 'https://www.linkedin.com/feed/'

    def test_login_page_is_navigated_to_at_most_once_and_polling_is_passive(self) -> None:
        page = FakePage(
            login_url='https://www.linkedin.com/login',
            feed_url=self.config.linkedin_feed_url,
            auto_auth_after_waits=2,
        )
        diagnostics = {
            'navigation_count': 0,
            'requested_navigation_count': 0,
            'current_url_changes': [],
            'authentication_marker': '',
        }
        session_module.attach_navigation_observer(page, diagnostics)
        session_module.navigate_linkedin_once(page, self.config.linkedin_feed_url, diagnostics=diagnostics)
        logged_in, reason = session_module.wait_for_manual_linkedin_login(page, diagnostics=diagnostics, timeout_seconds=5, poll_millis=1)
        self.assertTrue(logged_in)
        self.assertEqual(reason, '')
        self.assertEqual(page.goto_count, 1)
        self.assertEqual(page.reload_count, 0)
        self.assertEqual(diagnostics['requested_navigation_count'], 1)

    def test_connect_allows_remote_debugging_browser(self) -> None:
        self.config.linkedin_remote_debugging_url = 'http://127.0.0.1:9222'
        with patch.object(browser_module, 'open_linkedin_session', return_value=('pw', None, None, None, False, 'remote debugging session')) as opener:
            browser_module.open_local_linkedin_session(
                self.config,
                headed_default=True,
                allow_remote_debugging=True,
            )
        worker_config = opener.call_args.args[0]
        self.assertEqual(worker_config.linkedin_remote_debugging_url, 'http://127.0.0.1:9222')

    def test_non_interactive_browser_paths_disable_remote_debugging(self) -> None:
        self.config.linkedin_remote_debugging_url = 'http://127.0.0.1:9222'
        with patch.object(browser_module, 'open_linkedin_session', return_value=('pw', None, None, None, False, 'persistent profile')) as opener:
            browser_module.open_local_linkedin_session(
                self.config,
                headed_default=False,
                allow_remote_debugging=False,
            )
        worker_config = opener.call_args.args[0]
        self.assertEqual(worker_config.linkedin_remote_debugging_url, '')

    def test_connect_requires_remote_debugging_browser_when_requested(self) -> None:
        self.config.linkedin_remote_debugging_url = 'http://127.0.0.1:9222'
        with patch.object(browser_module, 'remote_debugging_is_available', return_value=False):
            with self.assertRaises(browser_module.RemoteBrowserUnavailableError):
                browser_module.open_local_linkedin_session(
                    self.config,
                    headed_default=True,
                    allow_remote_debugging=True,
                    require_remote_debugging=True,
                )

    def test_duplicate_connect_requests_do_not_launch_second_browser(self) -> None:
        first, should_spawn_first = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        second, should_spawn_second = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        self.assertTrue(should_spawn_first)
        self.assertFalse(should_spawn_second)
        self.assertEqual(first.active_job_id, second.active_job_id)

    def test_connect_claim_is_single_owner(self) -> None:
        connection, _ = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        first_claim = claim_channel_connect('linkedin', action_id=connection.active_job_id, worker_id='worker-a')
        second_claim = claim_channel_connect('linkedin', action_id=connection.active_job_id, worker_id='worker-b')
        self.assertIsNotNone(first_claim)
        self.assertIsNone(second_claim)

    def test_connect_status_moves_to_connected(self) -> None:
        connection, _ = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        page = FakePage(login_url='https://www.linkedin.com/login', feed_url=self.config.linkedin_feed_url)
        playwright = FakePlaywright()
        context = FakeContext()
        runtime = fake_plugin_runtime_for_session(self.config, lambda *args, **kwargs: (playwright, None, context, page, True, 'persistent profile'))
        with patch.object(connect_module, 'get_plugin_runtime', return_value=runtime):
            with patch.object(connect_module, 'inspect_linkedin_auth_state', return_value={'authenticated': False, 'reason': 'login', 'marker': 'login_url', 'current_url': page.login_url}):
                with patch.object(connect_module, 'wait_for_manual_linkedin_login', return_value=(True, '')):
                    result = connect_module.run_connect_action(self.config, channel_id='linkedin', action_id=connection.active_job_id, worker_id='worker-a', started_at='2026-06-20T08:00:00+02:00')
        self.assertIsNotNone(result)
        stored = get_channel_connection('linkedin')
        self.assertEqual(stored.status, 'connected')
        self.assertFalse(stored.active_job_id)
        self.assertTrue(playwright.stopped)
        self.assertTrue(context.closed)

    def test_connect_status_moves_to_needs_login_on_timeout(self) -> None:
        connection, _ = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        page = FakePage(login_url='https://www.linkedin.com/login', feed_url=self.config.linkedin_feed_url)
        playwright = FakePlaywright()
        context = FakeContext()
        runtime = fake_plugin_runtime_for_session(self.config, lambda *args, **kwargs: (playwright, None, context, page, True, 'persistent profile'))
        with patch.object(connect_module, 'get_plugin_runtime', return_value=runtime):
            with patch.object(connect_module, 'inspect_linkedin_auth_state', return_value={'authenticated': False, 'reason': 'login', 'marker': 'login_url', 'current_url': page.login_url}):
                with patch.object(connect_module, 'wait_for_manual_linkedin_login', return_value=(False, 'Timed out waiting for manual login.')):
                    result = connect_module.run_connect_action(self.config, channel_id='linkedin', action_id=connection.active_job_id, worker_id='worker-a', started_at='2026-06-20T08:00:00+02:00')
        self.assertIsNotNone(result)
        stored = get_channel_connection('linkedin')
        self.assertEqual(stored.status, 'needs_login')
        self.assertIn('Timed out waiting for manual login.', stored.last_error)

    def test_profile_ownership_is_released_after_completion(self) -> None:
        connection, _ = begin_channel_connect(
            'linkedin',
            mode='playwright_local',
            local_profile_path=str(self.config.linkedin_user_data_dir),
            capabilities_snapshot_json={'canConnect': True},
        )
        page = FakePage(login_url='https://www.linkedin.com/login', feed_url=self.config.linkedin_feed_url)
        playwright = FakePlaywright()
        context = FakeContext()
        runtime = fake_plugin_runtime_for_session(self.config, lambda *args, **kwargs: (playwright, None, context, page, True, 'persistent profile'))
        with patch.object(connect_module, 'get_plugin_runtime', return_value=runtime):
            with patch.object(connect_module, 'inspect_linkedin_auth_state', return_value={'authenticated': True, 'reason': '', 'marker': 'feed_url', 'current_url': page.feed_url}):
                result = connect_module.run_connect_action(self.config, channel_id='linkedin', action_id=connection.active_job_id, worker_id='worker-a', started_at='2026-06-20T08:00:00+02:00')
        self.assertIsNotNone(result)
        lock_path = Path(self._tmp.name) / 'studio_data' / 'locks' / 'linkedin.profile.lock'
        with open(lock_path, 'a+', encoding='utf-8') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == '__main__':
    unittest.main()
