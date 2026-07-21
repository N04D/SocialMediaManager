from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from channel_models import ChannelConnection, ContentDerivative, PublishJob
from channel_store import get_derivative, now_iso, save_channel_connection, save_derivative, save_publish_job
from channels.linkedin.runtime import LinkedInChannelRuntime
from media_runtime import MediaRuntime
from media_store import get_legacy_media_mapping, list_media_assets
from plugins.providers.local_media_storage import LocalMediaStorageConfig, LocalMediaStorageProvider
from src.core.browser.fake_provider import InMemoryBrowserProvider
from src.core.media import (
    MEDIA_ASSET_CONTRACT_VERSION,
    MEDIA_FRAMEWORK_VERSION,
    MEDIA_REFERENCE_CONTRACT_VERSION,
    MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION,
    InMemoryMediaStorageProvider,
    MediaDeleteOptions,
    MediaInput,
    MediaMaterializeOptions,
    MediaPluginRuntime,
    MediaStoreOptions,
    MediaUnsafePathError,
)
from src.core.plugins import PluginCapabilityError
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_plugin_runtime_phase2 import Config, linkedin_manifest, runtime_with_provider
from tests.test_support import isolated_channel_store

VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class MediaConfig(Config):
    pass


def _media_manifest(plugin_id: str = "provider.media.storage.memory", *, contract_version: str = "1.0"):
    return PluginManifest.from_dict(
        {
            "id": plugin_id,
            "name": plugin_id,
            "version": "0.1.0",
            "plugin_api_version": 1,
            "type": "provider",
            "entrypoint": "test",
            "capabilities": [
                "media.storage",
                "media.storage.store",
                "media.storage.read",
                "media.storage.materialize",
                "media.storage.delete",
            ],
            "dependencies": [],
            "config_schema": {"media_storage_provider_contract_version": contract_version},
        }
    )


def _runtime_with_media(config, browser_provider=None, media_provider=None):
    runtime = runtime_with_provider(browser_provider or InMemoryBrowserProvider())
    media_provider = media_provider or InMemoryMediaStorageProvider()
    manifest = _media_manifest(plugin_id=media_provider.provider_id)
    runtime.registry.register(manifest)
    runtime.runtimes[manifest.id] = PluginRuntime(
        manifest=manifest,
        instance=media_provider,
        status=PluginStatus.READY,
        services={"media_storage_provider": media_provider},
        health=media_provider.health_check() | {"default_priority": 5},
    )
    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    return runtime


class MediaStorageContractTests(unittest.TestCase):
    def _exercise_provider(self, provider) -> None:
        health = provider.health_check()
        self.assertEqual(health["media_storage_provider_contract_version"], "1.0")
        stored = provider.store(
            MediaInput(data=b"image-bytes", original_filename="photo.png", declared_mime_type="image/png"),
            MediaStoreOptions(workspace_id="linkedin", purpose="test"),
        )
        self.assertTrue(provider.exists(stored.storage_reference))
        self.assertNotIn("photo", stored.storage_reference)
        self.assertEqual(stored.checksum, provider.stat(stored.storage_reference).checksum)
        self.assertEqual(b"".join(provider.open_stream(stored.storage_reference)), b"image-bytes")
        materialized = provider.materialize(stored.storage_reference, MediaMaterializeOptions(purpose="test"))
        self.assertTrue(materialized.local_path.exists())
        provider.cleanup_materialization(materialized)
        self.assertFalse(materialized.local_path.exists())
        provider.delete(stored.storage_reference, MediaDeleteOptions(reason="contract test"))
        self.assertFalse(provider.exists(stored.storage_reference))

    def test_central_contract_versions(self) -> None:
        self.assertEqual(MEDIA_FRAMEWORK_VERSION, "0.2.0")
        self.assertEqual(MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_ASSET_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_REFERENCE_CONTRACT_VERSION, "1.0")

    def test_inmemory_provider_contract(self) -> None:
        self._exercise_provider(InMemoryMediaStorageProvider())

    def test_local_provider_contract_and_path_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = LocalMediaStorageProvider(storage_config=LocalMediaStorageConfig(root=Path(tmp) / "media-root"))
            self._exercise_provider(provider)
            with self.assertRaises(MediaUnsafePathError):
                provider.stat("../escape")

    def test_incompatible_media_provider_is_rejected(self) -> None:
        runtime = _runtime_with_media(MediaConfig())
        bad_manifest = _media_manifest(plugin_id="provider.media.storage.bad", contract_version="2.0")
        runtime.registry.register(bad_manifest)
        runtime.runtimes[bad_manifest.id] = PluginRuntime(
            manifest=bad_manifest,
            status=PluginStatus.READY,
            services={"media_storage_provider": InMemoryMediaStorageProvider()},
            health={"media_storage_provider_contract_version": "2.0", "default_priority": 1},
        )
        runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
        with self.assertRaises(PluginCapabilityError):
            runtime.resolve_provider("media.storage", preferred_provider_id="provider.media.storage.bad")


class MediaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = MediaConfig()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.media_dir.mkdir()
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.content_dir.mkdir()
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.runtime = _runtime_with_media(self.config)
        self.media_runtime = MediaRuntime(app_runtime=self.runtime, config=self.config)

    def test_import_asset_reference_materialize_and_soft_delete(self) -> None:
        asset = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
            created_by="test",
        )
        self.assertEqual(asset.status, "available")
        self.assertNotIn("post.png", asset.storage_reference)
        self.assertEqual(
            self.media_runtime.resolve_reference(asset.id, workspace_id="linkedin").reference, f"media-asset:{asset.id}"
        )
        with self.media_runtime.materialize(asset.id, workspace_id="linkedin", purpose="linkedin.image_publish") as mat:
            self.assertTrue(mat.local_path.exists())
            materialized_path = mat.local_path
        self.assertFalse(materialized_path.exists())
        deleted = self.media_runtime.soft_delete_asset(asset.id, workspace_id="linkedin", actor="test", reason="done")
        self.assertEqual(deleted.status, "deleted")

    def test_legacy_path_lazy_import_and_mapping(self) -> None:
        legacy = self.config.media_dir / "legacy.png"
        legacy.write_bytes(b"legacy-image")
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello",
                status="approved",
                generation_metadata_json={"image_paths": [str(legacy)]},
            )
        )
        asset = self.media_runtime.import_legacy_path(legacy, workspace_id="linkedin", derivative=derivative)
        self.assertEqual(get_legacy_media_mapping(legacy), asset.id)
        self.assertTrue(legacy.exists())
        updated = get_derivative("derivative-1")
        assert updated is not None
        self.assertIn(asset.id, updated.generation_metadata_json["media_asset_ids"])
        self.assertEqual(self.media_runtime.import_legacy_path(legacy, workspace_id="linkedin").id, asset.id)

    def test_unsafe_legacy_path_rejected(self) -> None:
        outside = Path(self.tmp.name).parent / "outside.png"
        outside.write_bytes(b"nope")
        self.addCleanup(outside.unlink, missing_ok=True)
        with self.assertRaises(MediaUnsafePathError):
            self.media_runtime.import_legacy_path(outside, workspace_id="linkedin")


class LinkedInMediaAssetPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = MediaConfig()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.media_dir.mkdir()
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.content_dir.mkdir()
        self.browser_provider = InMemoryBrowserProvider()
        self.browser_provider.evaluate_results = ["Hello LinkedIn"]
        self.runtime = _runtime_with_media(self.config, browser_provider=self.browser_provider)
        manifest = linkedin_manifest()
        self.runtime.registry.register(manifest)
        self.service = LinkedInChannelRuntime(manifest=manifest, app_runtime=self.runtime, config=self.config)
        self.runtime.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
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
            )
        )

    def _job(self, metadata: dict) -> PublishJob:
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello LinkedIn",
                status="approved",
                generation_metadata_json=metadata,
            )
        )
        return save_publish_job(
            PublishJob(
                id="publish-1",
                derivative_id=derivative.id,
                channel_id="linkedin",
                status="running",
                requested_at=now_iso(),
                run_mode="dry_run",
            )
        )

    def test_image_publish_with_media_asset_materializes_and_cleans_up(self) -> None:
        media_runtime = self.runtime.media_runtime(self.config)
        asset = media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        job = self._job({"media_asset_ids": [asset.id]})
        result = self.service.publish(job.id, worker_id="worker-a")
        self.assertEqual(result.status, "success")
        self.assertEqual(len(self.browser_provider.uploads), 1)
        uploaded_path = self.browser_provider.uploads[0][1]
        self.assertFalse(uploaded_path.exists())
        self.assertNotIn(asset.storage_reference, str(result.result_details_json))

    def test_image_publish_legacy_path_lazy_migrates(self) -> None:
        legacy = self.config.media_dir / "legacy.png"
        legacy.write_bytes(VALID_PNG)
        job = self._job({"image_paths": [str(legacy)]})
        result = self.service.publish(job.id, worker_id="worker-a")
        self.assertEqual(result.status, "success")
        self.assertEqual(len(list_media_assets(workspace_id="linkedin")), 1)
        self.assertTrue(legacy.exists())


class MediaBoundaryTests(unittest.TestCase):
    def test_fake_media_plugin_runtime_health(self) -> None:
        service = MediaPluginRuntime(plugin_id="media.fake.processor", capabilities=("media.image.inspect",))
        health = service.health_check()
        self.assertEqual(health["media_plugin_contract_version"], "1.0")
        self.assertEqual(health["capabilities"], ["media.image.inspect"])
        self.assertIn("media.storage.read", health["required_storage_capabilities"])

    def test_media_boundaries(self) -> None:
        core_text = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/media").glob("*.py"))
        self.assertNotIn("channels.", core_text)
        self.assertNotIn("src.core.browser", core_text)
        linkedin_text = Path("channels/linkedin/worker/publish.py").read_text(encoding="utf-8")
        self.assertNotIn("LocalMediaStorageProvider", linkedin_text)
        self.assertNotIn("plugins.providers.local_media_storage", linkedin_text)
        self.assertNotIn(
            "BrowserArtifact",
            "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/media").glob("*.py")),
        )


if __name__ == "__main__":
    unittest.main()
