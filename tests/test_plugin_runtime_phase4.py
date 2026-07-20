from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from channel_models import ChannelConnection, ContentDerivative, MetricJob, PublishedPost, PublishJob
from channel_store import (
    get_channel_connection,
    latest_metric_snapshot_for_post,
    now_iso,
    save_channel_connection,
    save_derivative,
    save_metric_job,
    save_publish_job,
    save_published_post,
)
from channels.linkedin.runtime import LinkedInChannelRuntime, LinkedInChannelRuntimeError
from channels.linkedin.targets import composer
from plugins.providers.legacy_browser import LegacyBrowserProvider
from src.core.browser import (
    BrowserInteractionError,
    BrowserSessionError,
    BrowserSessionOptions,
    FileBackedBrowserProfileLockManager,
)
from src.core.browser.fake_provider import InMemoryBrowserProvider
from src.core.media.fake_provider import InMemoryMediaStorageProvider
from src.core.plugins.manifest import PluginStatus
from src.core.plugins.runtime import PluginRuntime
from tests.test_media_framework_phase9 import _media_manifest
from tests.test_plugin_runtime_phase2 import (
    Config,
    FakeContext,
    FakePage,
    FakePlaywright,
    linkedin_manifest,
    runtime_with_provider,
)
from tests.test_support import isolated_channel_store


class Phase4InMemoryLinkedInTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir(parents=True)
        self.config.linkedin_browser_provider_id = ""
        self.config.media_dir = Path(self.tmp.name)
        self.config.content_dir = Path(self.tmp.name)

    def _runtime_with_channel(self, provider: InMemoryBrowserProvider):
        runtime = runtime_with_provider(provider)
        media_provider = InMemoryMediaStorageProvider()
        media_manifest = _media_manifest(plugin_id=media_provider.provider_id)
        runtime.registry.register(media_manifest)
        runtime.runtimes[media_manifest.id] = PluginRuntime(
            manifest=media_manifest,
            instance=media_provider,
            status=PluginStatus.READY,
            services={"media_storage_provider": media_provider},
            health=media_provider.health_check() | {"default_priority": 5},
        )
        manifest = linkedin_manifest()
        runtime.registry.register(manifest)
        service = LinkedInChannelRuntime(manifest=manifest, app_runtime=runtime, config=self.config)
        runtime.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"channel_runtime": service},
        )
        return runtime, service

    def _publish_job(self, *, run_mode: str = "dry_run", metadata: dict | None = None) -> PublishJob:
        derivative = ContentDerivative(
            id="derivative-1",
            source_document_id="source-1",
            channel_id="linkedin",
            output_type="linkedin_post",
            title="Post",
            body="Hello LinkedIn",
            status="approved",
            generation_metadata_json=metadata or {},
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        save_derivative(derivative)
        job = PublishJob(
            id="publish-1",
            derivative_id=derivative.id,
            channel_id="linkedin",
            status="running",
            requested_at=now_iso(),
            started_at=now_iso(),
            run_mode=run_mode,
        )
        return save_publish_job(job)

    def _metric_job(self, *, url: str = "https://www.linkedin.com/feed/update/urn:li:activity:1") -> MetricJob:
        post = PublishedPost(
            id="post-1",
            derivative_id="derivative-1",
            source_document_id="source-1",
            channel_id="linkedin",
            external_id="urn:li:activity:1",
            external_url=url,
            published_at=now_iso(),
            publish_job_id="publish-1",
            status="confirmed",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        save_published_post(post)
        job = MetricJob(
            id="metric-1",
            published_post_id=post.id,
            channel_id="linkedin",
            status="running",
            scheduled_for=now_iso(),
            requested_at=now_iso(),
            started_at=now_iso(),
        )
        return save_metric_job(job)

    def test_text_publish_uses_browser_session_and_closes(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_results = ["Hello LinkedIn"]
        _, service = self._runtime_with_channel(provider)
        job = self._publish_job()

        result = service.publish(job.id, worker_id="worker-a")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.last_step, "dry_run_complete")
        self.assertEqual(provider.sessions, {})
        self.assertTrue(any(action.action == "click" for action in provider.actions))
        self.assertTrue(any(action.action == "screenshot" for action in provider.actions))
        self.assertTrue(any(action.payload.get("profile_id") == "linkedin" for action in provider.actions))

    def test_image_publish_uploads_via_browser_session(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_results = ["Hello LinkedIn"]
        _, service = self._runtime_with_channel(provider)
        image_path = Path(self.tmp.name) / "image.png"
        image_path.write_bytes(b"fake")
        job = self._publish_job(metadata={"image_paths": [str(image_path)]})

        result = service.publish(job.id, worker_id="worker-a")

        self.assertEqual(result.status, "success")
        self.assertEqual(len(provider.uploads), 1)

    def test_publish_verification_failure_is_not_blind_success(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_results = ["Hello LinkedIn", []]
        for target in composer.CONFIRMATION_TARGETS:
            provider.configure_element(target, exists=False, enabled=False, visible=False)
        _, service = self._runtime_with_channel(provider)
        job = self._publish_job(run_mode="live")

        result = service.publish(job.id, worker_id="worker-a")

        self.assertEqual(result.status, "manual_verification_required")
        self.assertTrue(result.unknown_result)
        self.assertEqual(provider.sessions, {})

    def test_publish_upload_error_closes_session(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_results = ["Hello LinkedIn"]
        provider.simulate_failure("upload", BrowserInteractionError("upload.failed", "Upload failed."))
        _, service = self._runtime_with_channel(provider)
        image_path = Path(self.tmp.name) / "image.png"
        image_path.write_bytes(b"fake")
        job = self._publish_job(metadata={"image_paths": [str(image_path)]})

        result = service.publish(job.id, worker_id="worker-a")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "upload.failed")
        self.assertEqual(provider.sessions, {})

    def test_metrics_extracts_missing_and_zero_values(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_result = ["0 impressions", "12 views", "3 reactions"]
        _, service = self._runtime_with_channel(provider)
        job = self._metric_job()

        result = service.collect_metrics(job.id, worker_id="worker-a")
        snapshot = latest_metric_snapshot_for_post("post-1")

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.impressions, 0)
        self.assertEqual(snapshot.views, 12)
        self.assertIsNone(snapshot.comments)
        self.assertEqual(provider.sessions, {})

    def test_metrics_auth_required_updates_connection(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.navigation_redirects[self.config.linkedin_feed_url] = "https://www.linkedin.com/login"
        _, service = self._runtime_with_channel(provider)
        job = self._metric_job()

        result = service.collect_metrics(job.id, worker_id="worker-a")
        connection = get_channel_connection("linkedin")

        self.assertEqual(result.status, "needs_login")
        self.assertIsNotNone(connection)
        assert connection is not None
        self.assertEqual(connection.status, "needs_login")
        self.assertEqual(provider.sessions, {})

    def test_scraping_uses_browser_session_and_deduplicates(self) -> None:
        provider = InMemoryBrowserProvider()
        provider.evaluate_result = [
            {"url": "https://www.linkedin.com/feed/update/1", "text": "First"},
            {"url": "https://www.linkedin.com/feed/update/1", "text": "First duplicate"},
            {"url": "https://www.linkedin.com/feed/update/2", "text": "Second"},
        ]
        _, service = self._runtime_with_channel(provider)

        posts = service.scrape_posts(worker_id="worker-a")

        self.assertEqual([post["text"] for post in posts], ["First", "Second"])
        self.assertEqual(provider.sessions, {})

    def test_explicit_account_provider_has_no_silent_fallback(self) -> None:
        provider = InMemoryBrowserProvider()
        _, service = self._runtime_with_channel(provider)
        save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                browser_provider_id="provider.browser.missing",
            )
        )

        with self.assertRaises(LinkedInChannelRuntimeError):
            service.browser_provider(channel_id="linkedin")


class Phase4BrowserProviderContractTests(unittest.TestCase):
    def test_inmemory_provider_contract_for_used_operations(self) -> None:
        provider = InMemoryBrowserProvider()
        session = provider.create_session(
            BrowserSessionOptions(profile_id="linkedin", exclusive=True, start_url="https://www.linkedin.com/feed/")
        )
        target = composer.COMPOSER_EDITOR
        self.assertTrue(session.element_exists(target))
        self.assertTrue(session.element_visible(target))
        self.assertTrue(session.element_enabled(target))
        session.click(target)
        session.fill(target, "text")
        session.upload(composer.MEDIA_INPUT, Path("/tmp/image.png"))
        self.assertIsNotNone(session.screenshot())
        session.close()
        with self.assertRaises(BrowserSessionError):
            session.current_url()

    def test_legacy_session_translates_closed_operations(self) -> None:
        provider = LegacyBrowserProvider(
            config=Config(),
            open_session=lambda *a, **k: (FakePlaywright(), None, FakeContext(), FakePage(), True, "profile"),
            lock_manager=FileBackedBrowserProfileLockManager(Path(tempfile.mkdtemp()) / "legacy-locks"),
        )
        session = provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        session.close()
        with self.assertRaises(Exception) as ctx:
            session.navigate("https://www.linkedin.com/feed/")
        self.assertIn("already closed", str(ctx.exception))


class Phase4IsolationTests(unittest.TestCase):
    def test_legacy_bridge_is_removed_and_active_linkedin_code_is_page_free(self) -> None:
        self.assertFalse(hasattr(LegacyBrowserProvider, "acquire_legacy_execution_session"))
        active_files = [
            Path("channels/linkedin/runtime.py"),
            Path("channels/linkedin/worker/connect.py"),
            Path("channels/linkedin/worker/session.py"),
            Path("channels/linkedin/worker/publish.py"),
            Path("channels/linkedin/worker/metrics.py"),
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in active_files)
        self.assertNotIn("from pipeline", text)
        self.assertNotIn(".page", text)
        self.assertNotIn("page.", text)
        self.assertNotIn("playwright", text.lower().replace("playwright_local", ""))
