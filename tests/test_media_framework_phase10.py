from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from channel_models import ChannelConnection, ContentDerivative, PublishJob
from channel_store import now_iso, save_channel_connection, save_derivative, save_publish_job
from channels.linkedin.media_requirements import LINKEDIN_IMAGE_PUBLISH_REQUIREMENTS
from channels.linkedin.runtime import LinkedInChannelRuntime
from media_processing_runtime import deterministic_variant_key
from media_runtime import MediaRuntime
from media_store import list_media_variants
from src.core.browser.fake_provider import InMemoryBrowserProvider
from src.core.media import (
    MEDIA_FRAMEWORK_VERSION,
    MEDIA_INSPECTION_CONTRACT_VERSION,
    MEDIA_PROCESSING_CONTRACT_VERSION,
    MEDIA_REQUIREMENT_CONTRACT_VERSION,
    ChannelMediaRequirements,
    InMemoryMediaStorageProvider,
    MediaInput,
    MediaNotFoundError,
    MediaStatus,
    MediaVariantStatus,
)
from src.core.media.inspection import ImageInspector
from src.core.plugins.manifest import PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_media_framework_phase9 import _media_manifest
from tests.test_plugin_runtime_phase2 import Config, linkedin_manifest, runtime_with_provider
from tests.test_support import isolated_channel_store

VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02\x00\x00\x00\x03"
    b"\x08\x02\x00\x00\x00"
    b"\x12\x16\xf1M"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

VALID_JPEG = (
    b"\xff\xd8"
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xc0\x00\x11\x08\x00\x04\x00\x05\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    b"\xff\xd9"
)


class Phase10Config(Config):
    pass


def runtime_with_media(config, *, browser_provider=None, media_provider=None):
    runtime = runtime_with_provider(browser_provider or InMemoryBrowserProvider())
    provider = media_provider or InMemoryMediaStorageProvider()
    manifest = _media_manifest(plugin_id=provider.provider_id)
    runtime.registry.register(manifest)
    runtime.runtimes[manifest.id] = PluginRuntime(
        manifest=manifest,
        instance=provider,
        status=PluginStatus.READY,
        services={"media_storage_provider": provider},
        health=provider.health_check() | {"default_priority": 5},
    )
    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    runtime.media_runtime(config)
    runtime.media_processing_runtime(config)
    return runtime


class MediaFrameworkPhase10Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase10Config()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.runtime = runtime_with_media(self.config)
        self.media_runtime: MediaRuntime = self.runtime.media_runtime(self.config)
        self.processing_runtime = self.runtime.media_processing_runtime(self.config)

    def test_phase10_contract_versions(self) -> None:
        self.assertEqual(MEDIA_FRAMEWORK_VERSION, "0.2.0")
        self.assertEqual(MEDIA_INSPECTION_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_PROCESSING_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_REQUIREMENT_CONTRACT_VERSION, "1.0")

    def test_image_inspector_reads_png_and_jpeg_dimensions(self) -> None:
        inspector = ImageInspector()
        png = inspector.inspect_bytes(VALID_PNG, mime_type="image/png")
        jpeg = inspector.inspect_bytes(VALID_JPEG, mime_type="image/jpeg")
        self.assertEqual((png.status, png.width, png.height), ("passed", 2, 3))
        self.assertEqual((jpeg.status, jpeg.width, jpeg.height), ("passed", 5, 4))
        self.assertEqual(inspector.inspect_bytes(b"bad", mime_type="image/png").status, "failed")

    def test_import_asset_inspects_jpeg_and_png(self) -> None:
        png = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="safe.png", declared_mime_type="image/png"),
        )
        jpeg = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_JPEG, original_filename="safe.jpg", declared_mime_type="image/jpeg"),
        )
        self.assertEqual((png.width, png.height), (2, 3))
        self.assertEqual((jpeg.width, jpeg.height), (5, 4))
        self.assertEqual(png.metadata["image_inspection"]["status"], "passed")

    def test_linkedin_requirements_are_registered(self) -> None:
        requirement = self.processing_runtime.requirement_registry.get("channel.linkedin", "linkedin.image_publish")
        self.assertEqual(requirement, LINKEDIN_IMAGE_PUBLISH_REQUIREMENTS)
        self.assertEqual(requirement.requirement_version, "1.0")
        self.assertIn("image/png", requirement.allowed_mime_types)

    def test_resolve_channel_media_direct_use(self) -> None:
        asset = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        result = self.processing_runtime.resolve_channel_media(
            [asset.id],
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            capability="linkedin.image_publish",
        )
        self.assertEqual(len(result.selected), 1)
        self.assertTrue(result.selected[0].direct_use)
        self.assertEqual(result.selected[0].variant_id, "")
        self.assertEqual(result.requirement_version, "1.0")

    def test_variant_creation_is_deterministic_and_concurrency_safe(self) -> None:
        asset = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        requirement = ChannelMediaRequirements(
            channel_plugin_id="channel.linkedin",
            capability="linkedin.image_publish",
            requirement_id="linkedin.image.publish.v1",
            requirement_version="1.0",
            preferred_mime_type="image/jpeg",
        )
        expected_key = deterministic_variant_key(asset.id, asset.checksum, requirement)
        first = self.processing_runtime.ensure_variant(asset.id, workspace_id="linkedin", requirement=requirement)
        second = self.processing_runtime.ensure_variant(asset.id, workspace_id="linkedin", requirement=requirement)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.variant_key, expected_key)
        self.assertEqual(first.status, MediaVariantStatus.AVAILABLE.value)
        self.assertEqual(len(list_media_variants(asset_id=asset.id)), 1)

    def test_deleted_asset_is_rejected_by_resolution(self) -> None:
        asset = self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        asset.status = MediaStatus.DELETED.value
        from media_store import save_media_asset

        save_media_asset(asset)
        with self.assertRaises(MediaNotFoundError):
            self.processing_runtime.resolve_channel_media(
                [asset.id],
                workspace_id="linkedin",
                channel_plugin_id="channel.linkedin",
                capability="linkedin.image_publish",
            )


class LinkedInPhase10PublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase10Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.linkedin_user_data_dir.mkdir()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.browser_provider = InMemoryBrowserProvider()
        self.browser_provider.evaluate_results = ["Hello LinkedIn"]
        self.runtime = runtime_with_media(self.config, browser_provider=self.browser_provider)
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
                id="connection_linkedin", channel_id="linkedin", mode="playwright_local", status="connected"
            )
        )

    def test_linkedin_publish_uses_processing_runtime_and_records_evidence(self) -> None:
        asset = self.runtime.media_runtime(self.config).import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello LinkedIn",
                status="approved",
                generation_metadata_json={"media_asset_ids": [asset.id]},
            )
        )
        job = save_publish_job(
            PublishJob(
                id="publish-1",
                derivative_id=derivative.id,
                channel_id="linkedin",
                status="running",
                requested_at=now_iso(),
                run_mode="dry_run",
            )
        )
        result = self.service.publish(job.id, worker_id="worker-a")
        evidence = result.result_details_json["media_publication_evidence"][0]
        self.assertEqual(result.status, "success")
        self.assertEqual(evidence["source_asset_id"], asset.id)
        self.assertEqual(evidence["selected_variant_id"], "")
        self.assertTrue(evidence["direct_use"])
        self.assertEqual(evidence["requirement_version"], "1.0")
        self.assertNotIn("storage_reference", str(result.result_details_json))

    def test_legacy_path_migration_still_flows_through_processing(self) -> None:
        legacy = self.config.media_dir / "legacy.png"
        legacy.write_bytes(VALID_PNG)
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-legacy",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello LinkedIn",
                status="approved",
                generation_metadata_json={"image_paths": [str(legacy)]},
            )
        )
        job = save_publish_job(
            PublishJob(
                id="publish-legacy",
                derivative_id=derivative.id,
                channel_id="linkedin",
                status="running",
                requested_at=now_iso(),
                run_mode="dry_run",
            )
        )
        result = self.service.publish(job.id, worker_id="worker-a")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_details_json["uploaded_image_count"], 1)
        self.assertTrue(legacy.exists())


class MediaPhase10BoundaryTests(unittest.TestCase):
    def test_boundaries(self) -> None:
        core_text = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/media").glob("*.py"))
        self.assertNotIn("channels.", core_text)
        self.assertNotIn("src.core.browser", core_text)
        linkedin_text = Path("channels/linkedin/worker/publish.py").read_text(encoding="utf-8")
        self.assertNotIn("media_store", linkedin_text)
        self.assertNotIn("LocalMediaStorageProvider", linkedin_text)
        self.assertNotIn("plugins.providers.local_media_storage", linkedin_text)
        self.assertNotIn("storage_reference", linkedin_text)
        browser_contract = Path("src/core/browser/contracts.py").read_text(encoding="utf-8")
        self.assertIn('BROWSER_FRAMEWORK_VERSION = "1.0.0"', browser_contract)


if __name__ == "__main__":
    unittest.main()
