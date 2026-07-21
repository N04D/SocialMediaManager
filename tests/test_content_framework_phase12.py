from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import channel_store
from channel_models import ChannelConnection
from content_services import content_revision_checksum
from src.core.content import (
    CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION,
    CONTENT_FRAMEWORK_VERSION,
    CONTENT_ITEM_CONTRACT_VERSION,
    CONTENT_REQUIREMENTS_CONTRACT_VERSION,
    CONTENT_REVISION_CONTRACT_VERSION,
    PUBLICATION_PLAN_CONTRACT_VERSION,
    PUBLICATION_TARGET_CONTRACT_VERSION,
    ChannelContentVariantStatus,
    ContentConflictError,
    ContentValidationError,
)
from src.core.media import MediaInput
from tests.test_media_framework_phase10 import VALID_PNG
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class ContentFrameworkPhase12Tests(unittest.TestCase):
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
        self.runtime = runtime_with_library(self.config)
        self.content_service = self.runtime.content_service(self.config)
        self.planning = self.runtime.publication_planning_service(self.config)
        channel_store.save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )

    def create_content(self):
        return self.content_service.create_content(
            workspace_id="linkedin",
            title="Canonical",
            body="Hello LinkedIn\n\nFrom canonical content.",
            summary="Short",
            language="en",
            created_by="tester",
        )

    def test_contract_versions_are_central(self) -> None:
        self.assertEqual(CONTENT_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(CONTENT_ITEM_CONTRACT_VERSION, "1.0")
        self.assertEqual(CONTENT_REVISION_CONTRACT_VERSION, "1.0")
        self.assertEqual(CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION, "1.0")
        self.assertEqual(CONTENT_REQUIREMENTS_CONTRACT_VERSION, "1.0")
        self.assertEqual(PUBLICATION_PLAN_CONTRACT_VERSION, "1.0")
        self.assertEqual(PUBLICATION_TARGET_CONTRACT_VERSION, "1.0")

    def test_content_create_update_revision_checksum_and_conflict(self) -> None:
        item = self.create_content()
        revisions = self.content_service.revision_repository.list_by_content(item.id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].revision_number, 1)
        self.assertEqual(
            revisions[0].checksum,
            content_revision_checksum(
                title=item.title,
                body=item.body,
                summary=item.summary,
                language=item.language,
                metadata=item.metadata,
            ),
        )
        updated = self.content_service.update_content(
            item.id,
            workspace_id="linkedin",
            body="Changed body",
            expected_revision_id=item.current_revision_id,
        )
        self.assertNotEqual(updated.current_revision_id, item.current_revision_id)
        self.assertEqual(len(self.content_service.revision_repository.list_by_content(item.id)), 2)
        with self.assertRaises(ContentConflictError):
            self.content_service.update_content(
                item.id,
                workspace_id="linkedin",
                body="Conflict",
                expected_revision_id=item.current_revision_id,
            )

    def test_variant_validation_duplicate_ready_and_stale_detection(self) -> None:
        item = self.create_content()
        variant = self.content_service.create_variant(
            workspace_id="linkedin",
            content_item_id=item.id,
            channel_plugin_id="channel.linkedin",
            capability="channel.publish.text",
            body="Manual LinkedIn variant",
            created_by="tester",
        )
        self.assertEqual(variant.status, ChannelContentVariantStatus.READY.value)
        with self.assertRaises(ContentConflictError):
            self.content_service.create_variant(
                workspace_id="linkedin",
                content_item_id=item.id,
                channel_plugin_id="channel.linkedin",
                capability="channel.publish.text",
                body="Another ready variant",
            )
        self.content_service.update_content(
            item.id,
            workspace_id="linkedin",
            body="Changed canonical",
            expected_revision_id=item.current_revision_id,
        )
        self.assertEqual(
            self.content_service.variant_repository.get(variant.id).status,
            ChannelContentVariantStatus.STALE.value,
        )

    def test_linkedin_requirements_direct_use_and_no_truncation(self) -> None:
        item = self.create_content()
        revision, variant, result = self.content_service.resolve_channel_content(
            content_item_id=item.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            capability="channel.publish.text",
        )
        self.assertIsNone(variant)
        self.assertTrue(result.suitable)
        self.assertTrue(result.direct_use)
        self.assertEqual(revision.body, item.body)
        too_long = self.content_service.create_content(
            workspace_id="linkedin",
            title="Long",
            body="x" * 3001,
        )
        _revision, _variant, invalid = self.content_service.resolve_channel_content(
            content_item_id=too_long.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            capability="channel.publish.text",
        )
        self.assertFalse(invalid.suitable)
        self.assertEqual(too_long.body, "x" * 3001)

    def test_publication_plan_snapshot_queue_idempotency_and_safe_payload(self) -> None:
        item = self.create_content()
        media_runtime = self.runtime.media_runtime(self.config)
        asset = media_runtime.import_asset(
            workspace_id="linkedin",
            source=MediaInput(data=VALID_PNG, original_filename="plan.png", declared_mime_type="image/png"),
        )
        relation = self.runtime.media_library_service(self.config).attach_asset(
            workspace_id="linkedin",
            owner_type="content",
            owner_id=item.id,
            asset_id=asset.id,
            role="primary",
        )
        plan = self.planning.create_plan(
            workspace_id="linkedin",
            content_item_id=item.id,
            name="Plan",
            created_by="tester",
        )
        target = self.planning.add_target(
            plan.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            channel_account_id="linkedin",
            capability="channel.publish.text",
            media_relation_ids=[relation.id],
        )
        prepared = self.planning.prepare_target(target.id, workspace_id="linkedin", actor="tester")
        snapshot = prepared.metadata["snapshot"]
        serialized = json.dumps(snapshot)
        self.assertIn(relation.id, snapshot["media_relation_ids"])
        self.assertNotIn("storage_reference", serialized)
        self.assertNotIn("local_path", serialized)
        queued = self.planning.queue_target(
            target.id,
            workspace_id="linkedin",
            actor="tester",
            confirmation=True,
        )
        again = self.planning.queue_target(
            target.id,
            workspace_id="linkedin",
            actor="tester",
            confirmation=True,
        )
        self.assertEqual(queued.job_id, again.job_id)
        job = channel_store.get_publish_job(queued.job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.result_details_json["snapshot_checksum"], queued.snapshot_checksum)

    def test_queue_requires_confirmation_and_stale_targets_are_blocked(self) -> None:
        item = self.create_content()
        plan = self.planning.create_plan(workspace_id="linkedin", content_item_id=item.id, name="Plan")
        target = self.planning.add_target(
            plan.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            channel_account_id="linkedin",
            capability="channel.publish.text",
        )
        self.planning.prepare_target(target.id, workspace_id="linkedin")
        with self.assertRaises(ContentValidationError):
            self.planning.queue_target(target.id, workspace_id="linkedin", confirmation=False)
        prepared = self.planning.target_repository.get(target.id)
        prepared.snapshot_checksum = "changed"
        self.planning.target_repository.save(prepared)
        with self.assertRaises(ContentValidationError):
            self.planning.queue_target(target.id, workspace_id="linkedin", confirmation=True)

    def test_legacy_content_lazy_migration_does_not_rewrite_source(self) -> None:
        draft_dir = self.config.content_dir / "legacy"
        draft_dir.mkdir()
        (draft_dir / "metadata.yaml").write_text("id: legacy\ntitle: Legacy\nstatus: draft\n", encoding="utf-8")
        (draft_dir / "content.md").write_text("Legacy body\n", encoding="utf-8")
        before = (draft_dir / "content.md").read_text(encoding="utf-8")
        item = self.content_service.get_content("legacy", workspace_id="linkedin")
        self.assertEqual(item.source_type, "legacy_content")
        self.assertEqual((draft_dir / "content.md").read_text(encoding="utf-8"), before)
        again = self.content_service.get_content("legacy", workspace_id="linkedin")
        self.assertEqual(item.id, again.id)

    def test_integrity_health_and_boundaries(self) -> None:
        self.assertEqual(self.content_service.health_check()["status"], "ready")
        self.assertEqual(self.planning.health_check()["status"], "ready")
        self.assertIsInstance(self.content_service.scan_integrity(workspace_id="linkedin"), list)
        core_sources = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/content").glob("*.py"))
        self.assertNotIn("channels.", core_sources)
        self.assertNotIn("src.core.browser", core_sources)
        planning_source = Path("publication_planning.py").read_text(encoding="utf-8")
        self.assertNotIn("LinkedInChannelRuntime", planning_source)
        linkedin_publish = Path("channels/linkedin/worker/publish.py").read_text(encoding="utf-8")
        self.assertNotIn("ContentRepository", linkedin_publish)
        self.assertNotIn("PublicationPlanRepository", linkedin_publish)
