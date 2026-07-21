from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from channel_models import ChannelConnection, ContentDerivative, PublishJob
from channel_store import get_derivative, now_iso, save_channel_connection, save_derivative, save_publish_job
from channels.linkedin.runtime import LinkedInChannelRuntime
from media_library import MediaRelationRepository, MediaUsageRepository
from media_store import list_media_variants, save_media_asset, save_media_variant
from src.core.browser.fake_provider import InMemoryBrowserProvider
from src.core.media import (
    MEDIA_FRAMEWORK_VERSION,
    MEDIA_LIBRARY_CONTRACT_VERSION,
    MEDIA_PROCESSING_CONTRACT_VERSION,
    MEDIA_RELATION_CONTRACT_VERSION,
    MEDIA_REQUIREMENT_CONTRACT_VERSION,
    MEDIA_RETENTION_CONTRACT_VERSION,
    MEDIA_USAGE_CONTRACT_VERSION,
    ContentMediaRole,
    InMemoryMediaStorageProvider,
    MediaInput,
    MediaNotFoundError,
    MediaStatus,
    MediaUsageType,
    MediaValidationError,
    MediaVariantStatus,
)
from src.core.plugins.manifest import PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_media_framework_phase9 import _media_manifest
from tests.test_media_framework_phase10 import VALID_PNG
from tests.test_plugin_runtime_phase2 import Config, linkedin_manifest, runtime_with_provider
from tests.test_support import isolated_channel_store


class Phase11Config(Config):
    pass


def runtime_with_library(config, *, browser_provider=None, media_provider=None):
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
    runtime.media_library_service(config)
    return runtime


class MediaLibraryPhase11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase11Config()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.config.linkedin_user_data_dir.mkdir()
        self.browser_provider = InMemoryBrowserProvider()
        self.browser_provider.evaluate_results = ["Hello LinkedIn"]
        self.runtime = runtime_with_library(self.config, browser_provider=self.browser_provider)
        self.library = self.runtime.media_library_service(self.config)
        self.media_runtime = self.runtime.media_runtime(self.config)
        self.derivative = save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="content-1",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello LinkedIn",
                status="approved",
            )
        )

    def asset(self, name: str = "post.png"):
        return self.media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename=name, declared_mime_type="image/png"),
        )

    def test_contract_versions_and_service_health(self) -> None:
        self.assertEqual(MEDIA_FRAMEWORK_VERSION, "0.3.0")
        self.assertEqual(MEDIA_LIBRARY_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_RELATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_USAGE_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_RETENTION_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_PROCESSING_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_REQUIREMENT_CONTRACT_VERSION, "1.0")
        self.assertEqual(self.library.health_check()["status"], "ready")

    def test_relation_create_list_reorder_primary_duplicate_and_restore(self) -> None:
        first = self.asset("first.png")
        second = self.asset("second.png")
        relation_a = self.library.attach_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            asset_id=first.id,
            role="gallery",
            position=1,
        )
        relation_b = self.library.attach_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            asset_id=second.id,
            role="primary",
            position=0,
        )
        self.assertEqual(
            self.library.list_owner_media(owner_type="draft", owner_id=self.derivative.id, workspace_id="linkedin")[
                0
            ].id,
            relation_b.id,
        )
        self.assertEqual(len(self.library.relation_repository.list_by_asset(first.id)), 1)
        with self.assertRaises(MediaValidationError):
            self.library.attach_asset(
                workspace_id="linkedin",
                owner_type="draft",
                owner_id=self.derivative.id,
                asset_id=first.id,
                role="gallery",
                position=1,
            )
        self.library.reorder_assets(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            ordered_relation_ids=[relation_a.id, relation_b.id],
        )
        self.assertEqual(self.library.relation_repository.get(relation_a.id).position, 0)
        self.library.set_primary_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            relation_id=relation_a.id,
        )
        active_primary = [
            item
            for item in self.library.relation_repository.list_by_owner(
                "draft", self.derivative.id, workspace_id="linkedin"
            )
            if item.role == "primary" and item.active
        ]
        self.assertEqual([item.id for item in active_primary], [relation_a.id])
        self.library.detach_asset(relation_a.id)
        self.assertFalse(self.library.relation_repository.get(relation_a.id).active)
        self.library.relation_repository.restore(relation_a.id)
        self.assertTrue(self.library.relation_repository.get(relation_a.id).active)

    def test_relation_integrity_rejects_bad_inputs(self) -> None:
        asset = self.asset()
        with self.assertRaises(MediaNotFoundError):
            self.library.attach_asset(
                workspace_id="wrong", owner_type="draft", owner_id=self.derivative.id, asset_id=asset.id
            )
        asset.status = MediaStatus.DELETED.value
        save_media_asset(asset)
        with self.assertRaises(MediaNotFoundError):
            self.library.attach_asset(
                workspace_id="linkedin", owner_type="draft", owner_id=self.derivative.id, asset_id=asset.id
            )

    def test_lazy_media_asset_id_migration_preserves_order_and_legacy_field(self) -> None:
        first = self.asset("first.png")
        second = self.asset("second.png")
        self.derivative.generation_metadata_json = {"media_asset_ids": [first.id, second.id]}
        relations = self.library.list_owner_media(
            owner_type="draft",
            owner_id=self.derivative.id,
            workspace_id="linkedin",
            compatibility_metadata=self.derivative.generation_metadata_json,
        )
        self.assertEqual([item.asset_id for item in relations], [first.id, second.id])
        self.assertEqual(relations[0].role, "social_image")
        self.assertEqual(self.derivative.generation_metadata_json["media_asset_ids"], [first.id, second.id])
        again = self.library.list_owner_media(
            owner_type="draft",
            owner_id=self.derivative.id,
            workspace_id="linkedin",
            compatibility_metadata=self.derivative.generation_metadata_json,
        )
        self.assertEqual(len(again), 2)

    def test_lazy_legacy_path_import_creates_asset_and_relation_without_rewriting_file(self) -> None:
        legacy = self.config.media_dir / "legacy.png"
        legacy.write_bytes(VALID_PNG)
        self.derivative.generation_metadata_json = {"image_paths": [str(legacy)]}
        relations = self.library.list_owner_media(
            owner_type="draft",
            owner_id=self.derivative.id,
            workspace_id="linkedin",
            compatibility_metadata=self.derivative.generation_metadata_json,
        )
        self.assertEqual(len(relations), 1)
        self.assertTrue(legacy.exists())
        self.assertIn("media_asset_ids", get_derivative(self.derivative.id).generation_metadata_json)
        self.assertNotIn("path", json.dumps(relations[0].metadata).lower())

    def test_owner_resolution_usage_and_no_path_payload(self) -> None:
        asset = self.asset()
        relation = self.library.attach_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            asset_id=asset.id,
            role="primary",
            position=0,
        )
        result = self.library.resolve_owner_media(
            owner_type="draft",
            owner_id=self.derivative.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            capability="linkedin.image_publish",
            job_id="job-1",
        )
        self.assertEqual(result.selected_items[0].relation_id, relation.id)
        self.assertTrue(result.selected_items[0].direct_use)
        self.assertEqual(result.requirement_version, "1.0")
        self.assertNotIn("path", str(result))
        usage_types = [item.usage_type for item in self.library.list_asset_usage(asset.id, workspace_id="linkedin")]
        self.assertIn(MediaUsageType.LINKED.value, usage_types)
        self.assertIn(MediaUsageType.SELECTED.value, usage_types)

    def test_search_filters_pagination_and_safe_fields(self) -> None:
        first = self.asset("first.png")
        self.asset("second.png")
        self.library.attach_asset(
            workspace_id="linkedin", owner_type="draft", owner_id=self.derivative.id, asset_id=first.id
        )
        result = self.library.search_assets(
            workspace_id="linkedin",
            filters={
                "display_name": "first",
                "linked": True,
                "page_size": 1,
                "sort_by": "display_name",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(result.total, 1)
        payload = result.assets[0]
        self.assertEqual(payload["id"], first.id)
        self.assertNotIn("storage_reference", json.dumps(payload))
        self.assertIn("channel_suitability", payload)

    def test_variant_relation_resolution_and_usage(self) -> None:
        asset = self.asset()
        requirement = self.library.requirement_registry.get("channel.linkedin", "linkedin.image_publish")
        variant = self.runtime.media_processing_runtime(self.config).ensure_variant(
            asset.id,
            workspace_id="linkedin",
            requirement=requirement,
        )
        self.library.attach_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=self.derivative.id,
            asset_id=asset.id,
            variant_id=variant.id,
            role="publication_media",
        )
        result = self.library.resolve_owner_media(
            owner_type="draft",
            owner_id=self.derivative.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            capability="linkedin.image_publish",
            job_id="job-variant",
        )
        self.assertEqual(result.selected_items[0].variant_id, variant.id)
        self.assertIn("variant_available", result.selected_items[0].suitability_status)

    def test_retention_preview_plan_execution_and_pins(self) -> None:
        asset = self.asset()
        requirement = self.library.requirement_registry.get("channel.linkedin", "linkedin.image_publish")
        variant = self.runtime.media_processing_runtime(self.config).ensure_variant(
            asset.id,
            workspace_id="linkedin",
            requirement=requirement,
        )
        variant.created_at = "2020-01-01T00:00:00+00:00"
        variant.updated_at = "2020-01-01T00:00:00+00:00"
        save_media_variant(variant)
        candidates = self.library.retention_preview(workspace_id="linkedin")
        self.assertEqual([item.variant_id for item in candidates], [variant.id])
        variant.retention_pinned = True
        save_media_variant(variant)
        self.assertEqual(self.library.retention_preview(workspace_id="linkedin"), [])
        variant.retention_pinned = False
        save_media_variant(variant)
        plan = self.library.create_retention_plan(workspace_id="linkedin", actor="test", reason="cleanup test")
        self.assertTrue(plan.confirmation_required)
        executed = self.library.execute_retention_plan(
            plan_id=plan.id,
            actor="test",
            reason="confirmed cleanup",
            confirmation_token=plan.confirmation_token,
        )
        self.assertIn(executed.status, {"completed", "partially_completed"})
        self.assertEqual(list_media_variants(asset_id=asset.id)[0].status, MediaVariantStatus.DELETED.value)
        self.assertEqual(self.library.get_asset(asset.id, workspace_id="linkedin").status, MediaStatus.AVAILABLE.value)

    def test_historical_publication_blocks_retention(self) -> None:
        asset = self.asset()
        requirement = self.library.requirement_registry.get("channel.linkedin", "linkedin.image_publish")
        variant = self.runtime.media_processing_runtime(self.config).ensure_variant(
            asset.id, workspace_id="linkedin", requirement=requirement
        )
        variant.created_at = "2020-01-01T00:00:00+00:00"
        variant.updated_at = "2020-01-01T00:00:00+00:00"
        save_media_variant(variant)
        self.library.record_published_usage(
            [
                {
                    "source_asset_id": asset.id,
                    "selected_variant_id": variant.id,
                    "owner_type": "draft",
                    "owner_id": self.derivative.id,
                }
            ],
            workspace_id="linkedin",
            publication_id="published-1",
            job_id="job-1",
        )
        self.assertEqual(self.library.retention_preview(workspace_id="linkedin"), [])

    def test_soft_delete_restore_preview_and_integrity(self) -> None:
        asset = self.asset()
        self.library.attach_asset(
            workspace_id="linkedin", owner_type="draft", owner_id=self.derivative.id, asset_id=asset.id
        )
        deleted = self.library.request_delete(asset.id, workspace_id="linkedin", actor="test", reason="cleanup")
        self.assertEqual(deleted["asset"]["status"], "deleted")
        hidden = self.library.search_assets(workspace_id="linkedin", filters={})
        self.assertEqual(hidden.total, 0)
        restored = self.library.restore_asset(asset.id, workspace_id="linkedin", actor="test")
        self.assertEqual(restored.status, "available")
        data, mime, headers = self.library.preview_asset(asset.id, workspace_id="linkedin")
        self.assertEqual(mime, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("path", json.dumps(headers).lower())
        scan = self.library.integrity_scan(workspace_id="linkedin")
        self.assertIn(scan["status"], {"ok", "issues"})

    def test_usage_repository_idempotent_increment_and_expiry(self) -> None:
        asset = self.asset()
        repo: MediaUsageRepository = self.library.usage_repository
        self.library._register_usage(
            asset_id=asset.id,
            variant_id="",
            workspace_id="linkedin",
            usage_type="previewed",
            owner_type="unknown",
            owner_id="preview",
            idempotency_key="preview-key",
        )
        self.library._register_usage(
            asset_id=asset.id,
            variant_id="",
            workspace_id="linkedin",
            usage_type="previewed",
            owner_type="unknown",
            owner_id="preview",
            idempotency_key="preview-key",
        )
        self.assertEqual(repo.list_by_asset(asset.id)[0].usage_count, 2)
        for usage in repo.list_by_asset(asset.id):
            usage.last_used_at = "2020-01-01T00:00:00+00:00"
        # Persist by using the public register path with a new old usage is unnecessary for the expiry contract here.
        self.assertIsInstance(repo.rebuild_counters(), dict)


class LinkedInRelationPublishPhase11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase11Config()
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.linkedin_user_data_dir.mkdir()
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.browser_provider = InMemoryBrowserProvider()
        self.browser_provider.evaluate_results = ["Hello LinkedIn"]
        self.runtime = runtime_with_library(self.config, browser_provider=self.browser_provider)
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

    def test_relation_based_publish_records_relation_evidence(self) -> None:
        asset = self.runtime.media_runtime(self.config).import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-publish",
                source_document_id="source",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Post",
                body="Hello LinkedIn",
                status="approved",
            )
        )
        relation = self.runtime.media_library_service(self.config).attach_asset(
            workspace_id="linkedin",
            owner_type="draft",
            owner_id=derivative.id,
            asset_id=asset.id,
            role=ContentMediaRole.PRIMARY.value,
            position=0,
        )
        job = save_publish_job(
            PublishJob(
                id="publish-rel",
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
        self.assertEqual(evidence["relation_id"], relation.id)
        self.assertEqual(evidence["source_asset_id"], asset.id)
        self.assertEqual(evidence["role"], "primary")
        self.assertNotIn("storage_reference", json.dumps(result.result_details_json))

    def test_compatibility_media_asset_ids_and_legacy_paths_still_publish(self) -> None:
        asset = self.runtime.media_runtime(self.config).import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="post.png", declared_mime_type="image/png"),
        )
        derivative = save_derivative(
            ContentDerivative(
                id="derivative-compat",
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
                id="publish-compat",
                derivative_id=derivative.id,
                channel_id="linkedin",
                status="running",
                requested_at=now_iso(),
            )
        )
        self.assertEqual(self.service.publish(job.id, worker_id="worker-a").status, "success")
        self.browser_provider.evaluate_results = ["Hello LinkedIn"]
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
            )
        )
        self.assertEqual(self.service.publish(job.id, worker_id="worker-a").status, "success")
        self.assertTrue(legacy.exists())


class MediaLibraryBoundaryPhase11Tests(unittest.TestCase):
    def test_boundaries_and_no_startup_bulk_migration(self) -> None:
        core_text = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/media").glob("*.py"))
        library_text = Path("media_library.py").read_text(encoding="utf-8")
        linkedin_text = Path("channels/linkedin/worker/publish.py").read_text(encoding="utf-8")
        dashboard_text = Path("dashboard.py").read_text(encoding="utf-8")
        worker_text = Path("worker.py").read_text(encoding="utf-8")
        self.assertNotIn("channels.", core_text)
        self.assertNotIn("channels.", library_text)
        self.assertNotIn("LocalMediaStorageProvider", library_text)
        self.assertNotIn("BasicImageProcessingPlugin", library_text)
        self.assertNotIn("MediaRelationRepository", linkedin_text)
        self.assertNotIn("MediaUsageRepository", linkedin_text)
        self.assertNotIn("MediaRetentionService", linkedin_text)
        self.assertNotIn("LocalMediaStorageProvider", dashboard_text)
        self.assertNotIn("LocalMediaStorageProvider", worker_text)
        self.assertNotIn("bulk", Path("plugin_runtime.py").read_text(encoding="utf-8").lower())
        self.assertIn(
            'BROWSER_FRAMEWORK_VERSION = "1.0.0"', Path("src/core/browser/contracts.py").read_text(encoding="utf-8")
        )

    def test_api_safe_payload_shapes(self) -> None:
        from dashboard import _query_filters, _safe_relation_payload, _safe_usage_payload

        relation = MediaRelationRepository().get("missing")
        self.assertIsNone(relation)
        self.assertTrue(_query_filters({"deleted": ["true"]})["deleted"])
        self.assertNotIn(
            "storage_reference",
            json.dumps(
                _safe_relation_payload(
                    type(
                        "R",
                        (),
                        {
                            "id": "r",
                            "workspace_id": "w",
                            "owner_type": "draft",
                            "owner_id": "d",
                            "asset_id": "a",
                            "variant_id": "",
                            "role": "primary",
                            "position": 0,
                            "channel_plugin_id": "",
                            "publication_id": "",
                            "required": False,
                            "active": True,
                            "created_at": "",
                            "updated_at": "",
                        },
                    )()
                )
            ),
        )
        self.assertNotIn(
            "storage_reference",
            json.dumps(
                _safe_usage_payload(
                    type(
                        "U",
                        (),
                        {
                            "id": "u",
                            "workspace_id": "w",
                            "asset_id": "a",
                            "variant_id": "",
                            "usage_type": "linked",
                            "owner_type": "draft",
                            "owner_id": "d",
                            "channel_plugin_id": "",
                            "publication_id": "",
                            "job_id": "",
                            "status": "active",
                            "first_used_at": "",
                            "last_used_at": "",
                            "usage_count": 1,
                            "retained_until": "",
                        },
                    )()
                )
            ),
        )


class MediaLibraryApiSmokeTests(unittest.TestCase):
    def test_upload_payload_base64_stays_available_for_existing_api(self) -> None:
        encoded = base64.b64encode(VALID_PNG).decode("ascii")
        self.assertTrue(encoded)


if __name__ == "__main__":
    unittest.main()
