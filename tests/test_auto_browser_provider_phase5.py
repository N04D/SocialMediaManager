from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from channel_models import ChannelConnection, ContentDerivative, MetricJob, PublishedPost, PublishJob
from channel_store import (
    now_iso,
    save_channel_connection,
    save_derivative,
    save_metric_job,
    save_publish_job,
    save_published_post,
)
from channels.linkedin.runtime import LinkedInChannelRuntime
from channels.linkedin.targets import composer
from plugin_runtime import bootstrap_plugins
from plugins.providers.auto_browser import AutoBrowserConfig, AutoBrowserProvider
from plugins.providers.auto_browser.provider import PROVIDER_ID
from plugins.providers.auto_browser.transport import AutoBrowserHttpTransport
from src.core.browser import (
    BrowserSessionError,
    BrowserSessionOptions,
    BrowserTarget,
    BrowserUnavailableError,
    FileBackedBrowserProfileLockManager,
    HumanTakeoverRequest,
)
from src.core.plugins import PluginCapabilityError
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_plugin_runtime_phase2 import Config, linkedin_manifest, provider_manifest, runtime_with_provider
from tests.test_support import isolated_channel_store


class FakeAutoBrowserTransport:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.actions: list[tuple[str, str, dict[str, Any]]] = []
        self.closed: list[str] = []
        self.saved_profiles: list[str] = []
        self.fail_health = False
        self.fail_create = False
        self.elements = [
            {
                "id": "start-post",
                "role": "button",
                "name": "Start a post",
                "text": "Start a post",
                "visible": True,
                "enabled": True,
            },
            {
                "id": "editor",
                "role": "textbox",
                "text": "",
                "attributes": {"css": composer.COMPOSER_EDITOR.css},
                "visible": True,
                "enabled": True,
            },
            {"id": "media", "attributes": {"css": composer.MEDIA_INPUT.css}, "visible": True, "enabled": True},
            {"id": "post", "role": "button", "name": "Post", "text": "Post", "visible": True, "enabled": True},
        ]
        self.evaluate_results: list[Any] = []

    def health(self) -> dict[str, Any]:
        if self.fail_health:
            from plugins.providers.auto_browser.errors import AutoBrowserConnectionError

            raise AutoBrowserConnectionError("down")
        return {"status": "ok"}

    def ready(self) -> dict[str, Any]:
        return {"status": "ready"}

    def server_info(self) -> dict[str, Any]:
        return {
            "version": "1.4.0",
            "features": {
                "takeover": True,
                "auth_profiles": True,
                "uploads": True,
                "evaluation": True,
                "screenshots": True,
            },
        }

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.fail_create:
            from plugins.providers.auto_browser.errors import AutoBrowserConnectionError

            raise AutoBrowserConnectionError("create failed")
        remote_id = f"remote-{len(self.sessions) + 1}"
        self.sessions[remote_id] = {
            "id": remote_id,
            "url": payload.get("start_url") or "about:blank",
            "title": "LinkedIn",
        }
        return {"session_id": remote_id, "status": "active"}

    def get_session(self, remote_session_id: str) -> dict[str, Any]:
        return self.sessions[remote_session_id]

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self.sessions.values())

    def close_session(self, remote_session_id: str) -> dict[str, Any]:
        self.closed.append(remote_session_id)
        self.sessions.pop(remote_session_id, None)
        return {"status": "closed"}

    def observe(self, remote_session_id: str, *, limit: int = 80, preset: str = "normal") -> dict[str, Any]:
        session = self.sessions.get(remote_session_id, {})
        return {"url": session.get("url", "about:blank"), "title": session.get("title", ""), "elements": self.elements}

    def navigate(self, remote_session_id: str, url: str) -> dict[str, Any]:
        self.sessions[remote_session_id]["url"] = url
        self.actions.append((remote_session_id, "navigate", {"url": url}))
        return {"status": "ok"}

    def perform_action(
        self, remote_session_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.actions.append((remote_session_id, action, payload or {}))
        return {"status": "ok"}

    def screenshot(self, remote_session_id: str, *, full_page: bool = True) -> dict[str, Any]:
        return {"artifact_id": "shot-1", "kind": "screenshot", "content_type": "image/png"}

    def evaluate(self, remote_session_id: str, script: str, arg: Any | None = None) -> Any:
        if self.evaluate_results:
            return self.evaluate_results.pop(0)
        return None

    def create_takeover(self, remote_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"takeover_id": "remote-takeover", "viewer_url": "http://internal.example/viewer?token=secret"}

    def save_auth_profile(self, remote_session_id: str, profile_name: str) -> dict[str, Any]:
        self.saved_profiles.append(profile_name)
        return {"profile_name": profile_name}

    def list_auth_profiles(self) -> list[dict[str, Any]]:
        return [{"profile_name": "profile"}]

    def get_auth_profile(self, profile_name: str) -> dict[str, Any]:
        return {"profile_name": profile_name}

    def delete_auth_profile(self, profile_name: str) -> dict[str, Any]:
        return {"deleted": profile_name}


class AutoBrowserProviderPhase5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.transport = FakeAutoBrowserTransport()
        self.provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(Path(self.tmp.name) / "uploads"),
            ),
            transport=self.transport,
            lock_manager=FileBackedBrowserProfileLockManager(Path(self.tmp.name) / "locks"),
            mapping_path=Path(self.tmp.name) / "sessions.json",
        )

    def test_manifest_validates_and_bootstrap_registers_disabled_provider(self) -> None:
        manifest = PluginManifest.from_dict(
            json.loads(Path("plugins/providers/auto_browser/plugin.manifest.json").read_text())
        )
        self.assertEqual(manifest.id, PROVIDER_ID)
        config = Config()
        config.auto_browser_enabled = False
        runtime = bootstrap_plugins(config, strict=False)
        self.assertIn(PROVIDER_ID, runtime.runtimes)
        self.assertEqual(runtime.runtimes[PROVIDER_ID].status, PluginStatus.DISABLED)
        self.assertEqual(runtime.resolve_provider("browser.session").manifest.id, "provider.browser.legacy")

    def test_provider_contract_session_actions_takeover_and_cleanup(self) -> None:
        session = self.provider.create_session(
            BrowserSessionOptions(profile_id="linkedin", start_url="https://www.linkedin.com/feed/", exclusive=True)
        )
        session.navigate("https://www.linkedin.com/feed/")
        self.assertTrue(session.element_exists(BrowserTarget(role="button", accessible_name="Start a post")))
        session.click(BrowserTarget(role="button", accessible_name="Start a post"))
        session.fill(composer.COMPOSER_EDITOR, "Hello")
        artifact = session.screenshot()
        takeover = self.provider.request_human_takeover(
            request=HumanTakeoverRequest(
                session_id=session.session_id,
                reason="login",
            )
        )
        self.assertEqual(artifact.metadata["provider_id"], PROVIDER_ID)
        self.assertNotIn("token=secret", json.dumps(takeover))
        session.close()
        self.assertEqual(self.provider.sessions, {})
        self.assertFalse(self.provider.profile_status("linkedin").busy)

    def test_lock_released_after_partial_creation_failure(self) -> None:
        self.transport.fail_create = True
        with self.assertRaises(BrowserUnavailableError):
            self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        self.assertFalse(self.provider.profile_status("linkedin").busy)

    def test_closed_session_rejects_actions(self) -> None:
        session = self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        session.close()
        with self.assertRaises(BrowserSessionError):
            session.current_url()

    def test_auth_profile_name_is_stable_and_not_profile_id(self) -> None:
        first = self.provider.auth_profile_name("person@example.com")
        second = self.provider.auth_profile_name("person@example.com")
        self.assertEqual(first, second)
        self.assertNotIn("person", first)
        self.assertNotIn("@", first)

    def test_auto_browser_can_be_explicitly_resolved_without_linkedin_import(self) -> None:
        runtime = runtime_with_provider(object())
        manifest = provider_manifest(plugin_id=PROVIDER_ID)
        runtime.registry.register(manifest)
        runtime.runtimes[PROVIDER_ID] = PluginRuntime(
            manifest=manifest,
            instance=self.provider,
            status=PluginStatus.READY,
            services={"browser_provider": self.provider},
            health={"default_priority": 50},
        )
        runtime.runtimes["provider.browser.legacy"].health = {"default_priority": 10}
        runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
        self.assertIs(runtime.browser_provider(preferred_provider_id=PROVIDER_ID), self.provider)
        self.assertEqual(runtime.browser_provider().__class__.__name__, "object")

    def test_pipeline_legacy_flow_blocks_explicit_auto_browser(self) -> None:
        config = Config()
        config.linkedin_browser_provider_id = ""
        save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                browser_provider_id=PROVIDER_ID,
            )
        )
        previous_pipeline = sys.modules.pop("pipeline", None)
        with self.assertRaises(RuntimeError):
            try:
                from pipeline import ensure_legacy_pipeline_linkedin_allowed

                ensure_legacy_pipeline_linkedin_allowed(config)
            finally:
                if previous_pipeline is not None:
                    sys.modules["pipeline"] = previous_pipeline


class AutoBrowserLinkedInIndependenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir(parents=True)
        self.transport = FakeAutoBrowserTransport()
        self.transport.evaluate_results = ["Hello LinkedIn"]
        self.provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(Path(self.tmp.name) / "uploads"),
            ),
            transport=self.transport,
            lock_manager=FileBackedBrowserProfileLockManager(Path(self.tmp.name) / "locks"),
            mapping_path=Path(self.tmp.name) / "sessions.json",
        )
        self.runtime = runtime_with_provider(object())
        manifest = provider_manifest(plugin_id=PROVIDER_ID)
        self.runtime.registry.register(manifest)
        self.runtime.runtimes[PROVIDER_ID] = PluginRuntime(
            manifest=manifest,
            instance=self.provider,
            status=PluginStatus.READY,
            services={"browser_provider": self.provider},
            health={"default_priority": 50},
        )
        self.runtime.resolver = ProviderResolver(self.runtime.registry, self.runtime.runtimes)
        linkedin = linkedin_manifest()
        self.runtime.registry.register(linkedin)
        self.service = LinkedInChannelRuntime(manifest=linkedin, app_runtime=self.runtime, config=self.config)
        self.runtime.runtimes[linkedin.id] = PluginRuntime(
            manifest=linkedin,
            instance=self.service,
            status=PluginStatus.READY,
            services={"channel_runtime": self.service},
        )
        save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                browser_provider_id=PROVIDER_ID,
            )
        )

    def test_text_publish_uses_auto_browser_provider_and_closes(self) -> None:
        save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Title",
                body="Hello LinkedIn",
                status="approved",
            )
        )
        job = save_publish_job(
            PublishJob(
                id="publish-1",
                derivative_id="derivative-1",
                channel_id="linkedin",
                status="running",
                requested_at=now_iso(),
                run_mode="dry_run",
            )
        )
        result = self.service.publish(job.id, worker_id="worker-a")
        self.assertEqual(result.status, "success")
        self.assertTrue(any(action[1] == "click" for action in self.transport.actions))
        self.assertEqual(self.provider.sessions, {})

    def test_metrics_and_scraping_use_auto_browser_provider(self) -> None:
        self.transport.evaluate_results = [
            ["0 impressions", "12 views"],
            [{"url": "https://www.linkedin.com/feed/update/1", "text": "One"}],
        ]
        save_published_post(
            PublishedPost(
                id="post-1",
                derivative_id="derivative-1",
                source_document_id="source",
                channel_id="linkedin",
                external_id="1",
                external_url="https://www.linkedin.com/feed/update/1",
                published_at=now_iso(),
                publish_job_id="publish-1",
                status="confirmed",
            )
        )
        metric = save_metric_job(
            MetricJob(
                id="metric-1",
                published_post_id="post-1",
                channel_id="linkedin",
                status="running",
                scheduled_for=now_iso(),
                requested_at=now_iso(),
            )
        )
        self.assertEqual(self.service.collect_metrics(metric.id, worker_id="worker-a").status, "success")
        posts = self.service.scrape_posts(worker_id="worker-a")
        self.assertEqual(posts[0]["text"], "One")

    def test_no_silent_fallback_for_unavailable_explicit_auto_browser(self) -> None:
        self.runtime.runtimes[PROVIDER_ID].status = PluginStatus.ERROR
        with self.assertRaises(PluginCapabilityError):
            self.runtime.browser_provider(preferred_provider_id=PROVIDER_ID)


class _Controller(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        self._respond({"status": "ok", "version": "1.4.0"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        _Controller.calls.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "operator": self.headers.get("X-Operator-ID", ""),
                "request_id": self.headers.get("X-Request-ID", ""),
                "body": json.loads(body.decode("utf-8")),
            }
        )
        self._respond({"session_id": "remote-1", "result": "ok"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _respond(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class AutoBrowserTransportTests(unittest.TestCase):
    def test_transport_sends_auth_operator_and_correlation_headers(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Controller)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        _Controller.calls.clear()
        config = AutoBrowserConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}",
            bearer_token="secret-token",
            operator_id="operator-a",
        )
        transport = AutoBrowserHttpTransport(config)
        transport.create_session({"name": "local"})
        call = _Controller.calls[-1]
        self.assertEqual(call["authorization"], "Bearer secret-token")
        self.assertEqual(call["operator"], "operator-a")
        self.assertTrue(call["request_id"])
