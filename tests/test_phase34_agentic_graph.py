from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import channel_store
from channel_models import ChannelConnection
from content_services import DeterministicClipCandidateTransformation
from src.core.content import (
    Campaign,
    ContentValidationError,
    Entity,
    Outcome,
    Playbook,
    PolicyRule,
    TimelineSegment,
    TransformationContract,
)
from src.core.plugins import PluginFamily, PluginRegistry, family_for_capability
from src.core.plugins.manifest import PluginManifest
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class Phase34AgenticGraphTests(unittest.TestCase):
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
        self.content = self.runtime.content_service(self.config)
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

    def test_legacy_written_draft_maps_to_written_primary_source_without_rewrite(self) -> None:
        draft_dir = self.config.content_dir / "legacy"
        draft_dir.mkdir()
        metadata = "id: legacy\ntitle: Legacy\nstatus: draft\n"
        body = "Legacy body\n"
        (draft_dir / "metadata.yaml").write_text(metadata, encoding="utf-8")
        (draft_dir / "content.md").write_text(body, encoding="utf-8")
        item = self.content.get_content("legacy", workspace_id="linkedin")
        self.assertEqual(item.source_type, "legacy_content")
        self.assertEqual(item.primary_source_type, "written")
        self.assertEqual(item.canonical_text_representation, "Legacy body")
        self.assertEqual((draft_dir / "content.md").read_text(encoding="utf-8"), body)

    def test_new_written_and_youtube_sources_preserve_transcript_provenance_across_restart(self) -> None:
        written = self.content.create_written_content(
            workspace_id="linkedin", title="Written", body="Canonical written body", created_by="tester"
        )
        youtube = self.content.create_youtube_source_content(
            workspace_id="linkedin",
            youtube_url="https://youtube.test/watch?v=abc123",
            video_id="abc123",
            title="Video",
            transcript="Original transcript",
            edited_transcript="Edited transcript",
            transcript_provenance={"provider": "paste_import"},
            created_by="tester",
        )
        restarted = runtime_with_library(self.config).content_service(self.config)
        loaded = restarted.get_content(youtube.id, workspace_id="linkedin")
        self.assertEqual(written.primary_source_type, "written")
        self.assertEqual(loaded.primary_source_type, "youtube_video")
        self.assertEqual(loaded.canonical_text_representation, "Edited transcript")
        self.assertEqual(loaded.canonical_metadata["transcript_original"], "Original transcript")
        self.assertTrue(loaded.canonical_metadata["transcript_changed"])
        self.assertEqual(loaded.source_provenance["provider"], "paste_import")

    def test_revision_and_variant_preserve_source_linkage(self) -> None:
        item = self.content.create_youtube_source_content(
            workspace_id="linkedin",
            youtube_url="https://youtu.be/v",
            video_id="v",
            title="Video",
            transcript="Transcript",
        )
        revision = self.content.revision_repository.current(item)
        variant = self.content.create_variant(
            workspace_id="linkedin",
            content_item_id=item.id,
            channel_plugin_id="channel.linkedin",
            capability="channel.publish.text",
            body="LinkedIn variant",
            metadata={"campaign_id": "campaign-1", "intent_id": "grow_audience", "transformation_run_id": "run-1"},
        )
        self.assertEqual(revision.primary_source_type, "youtube_video")
        self.assertEqual(variant.primary_source_type, "youtube_video")
        self.assertEqual(variant.campaign_id, "campaign-1")
        self.assertEqual(variant.intent_id, "grow_audience")
        self.assertEqual(variant.transformation_run_id, "run-1")

    def test_entity_relationships_outcomes_campaigns_playbooks_and_policy_validation(self) -> None:
        graph = self.content.graph_service
        article = graph.save_entity(Entity(id="entity-article", entity_type="article", title="Sabr article"))
        product = graph.save_entity(Entity(id="entity-product", entity_type="product", title="Sabr shirt"))
        relationship = graph.add_relationship(
            workspace_id="linkedin",
            from_entity_id=article.id,
            relationship_type="semantically_related_to",
            to_entity_id=product.id,
            metadata={"reason": "shared topic"},
            provenance={"actor_type": "agent", "provider": "test"},
        )
        campaign = graph.save_campaign(
            Campaign(
                id="campaign-1",
                workspace_id="linkedin",
                intent_id="sell_product",
                name="Commerce content",
                source_entity_ids=(article.id, product.id),
            )
        )
        outcome = graph.save_outcome(
            Outcome(
                id="outcome-1",
                workspace_id="linkedin",
                outcome_type="purchase",
                subject_entity_id=product.id,
                value=None,
                status="not_collected",
            )
        )
        playbook = graph.save_playbook(
            Playbook(
                id="playbook-commerce",
                name="E-commerce Content Campaign",
                intent_id="sell_product",
                required_capabilities=("commerce.product_catalog", "channel.linkedin", "outcome.sale"),
                policies=("policy-confirm",),
                success_metrics=("purchase",),
            )
        )
        self.assertEqual(relationship.relationship_type, "semantically_related_to")
        self.assertEqual(campaign.intent_id, "sell_product")
        self.assertEqual(outcome.status, "not_collected")
        self.assertIn("commerce.product_catalog", playbook.required_capabilities)
        ok, code = graph.validate_policy(
            PolicyRule(
                id="policy-confirm", description="Never publish without confirmation", effect="require_confirmation"
            )
        )
        self.assertTrue(ok, code)
        bad_ok, bad_code = graph.validate_policy(
            PolicyRule(id="policy-exec", description="bad", conditions={"exec": "nope"})
        )
        self.assertFalse(bad_ok)
        self.assertEqual(bad_code, "policy.executable_condition_forbidden")

    def test_capability_and_plugin_family_discovery_supports_commerce_channels_and_transformations(self) -> None:
        registry = PluginRegistry()
        for payload in [
            {
                "id": "source.youtube",
                "name": "YouTube",
                "version": "0.1",
                "plugin_api_version": 1,
                "type": "content",
                "entrypoint": "x",
                "status": "ready",
                "capabilities": ["source.youtube", "asset.transcript"],
            },
            {
                "id": "clipper",
                "name": "Clipper",
                "version": "0.1",
                "plugin_api_version": 1,
                "type": "media",
                "entrypoint": "x",
                "status": "ready",
                "capabilities": [
                    "transformation.accepts.asset.transcript",
                    "transformation.produces.asset.short_video",
                ],
            },
            {
                "id": "channel.linkedin",
                "name": "LinkedIn",
                "version": "0.1",
                "plugin_api_version": 1,
                "type": "channel",
                "entrypoint": "x",
                "status": "ready",
                "capabilities": ["channel.linkedin", "action.publish", "outcome.social_metrics"],
            },
            {
                "id": "shop",
                "name": "Shop",
                "version": "0.1",
                "plugin_api_version": 1,
                "type": "content",
                "entrypoint": "x",
                "status": "ready",
                "capabilities": ["commerce.product_catalog", "entity.product", "outcome.sale"],
            },
        ]:
            registry.register(PluginManifest.from_dict(payload))
        self.assertEqual(family_for_capability("commerce.product_catalog"), PluginFamily.COMMERCE)
        self.assertEqual(registry.producers_for("asset.short_video")[0].id, "clipper")
        self.assertEqual(registry.consumers_for("asset.transcript")[0].id, "clipper")
        self.assertEqual(registry.providers_for("channel.linkedin")[0].id, "channel.linkedin")
        self.assertEqual(registry.providers_for("commerce.product_catalog")[0].id, "shop")
        self.assertIn("commerce", registry.capabilities_by_family())

    def test_agent_context_and_attribution_chain_retrieval(self) -> None:
        graph = self.content.graph_service
        source = graph.save_entity(Entity(id="release-1", entity_type="release", source_plugin="github", title="v1"))
        item = self.content.create_content(
            workspace_id="linkedin",
            title="Release notes",
            body="Changelog",
            primary_source_type="github_release",
            primary_source_entity_id=source.id,
            canonical_text_representation="Changelog",
        )
        revision = self.content.revision_repository.current(item)
        transformation = TransformationContract(
            id="transformation.release.social",
            plugin_id="release-social",
            accepts=("entity.release",),
            produces=("variant.social_text",),
        )
        run = graph.record_transformation_run(
            workspace_id="linkedin", transformation=transformation, input_refs=(source.id,), output_refs=(revision.id,)
        )
        variant = self.content.create_variant(
            workspace_id="linkedin",
            content_item_id=item.id,
            channel_plugin_id="channel.linkedin",
            capability="channel.publish.text",
            body="Release social variant",
            metadata={"transformation_run_id": run.id},
        )
        context = graph.agent_context(workspace_id="linkedin", content_service=self.content)
        self.assertEqual(context["primary_sources"][0]["primary_source_entity_id"], source.id)
        self.assertTrue(any(entry["id"] == run.id for entry in context["transformations"]))
        self.assertTrue(any(entry["id"] == variant.id for entry in context["variants"]))

    def test_deterministic_clip_candidate_transformation_and_synthetic_asset_contract(self) -> None:
        transformer = DeterministicClipCandidateTransformation()
        candidates = transformer.run(
            [
                TimelineSegment(start_time=0, end_time=12, text="Intro"),
                TimelineSegment(
                    start_time=12, end_time=58, text="Why this launch matters and how creators can reuse it."
                ),
                TimelineSegment(start_time=58, end_time=110, text="Closing notes"),
            ]
        )
        self.assertEqual(candidates[0].start, 12)
        self.assertGreater(candidates[0].score, candidates[-1].score)
        missing = transformer.render_synthetic_short_asset(candidates[0])
        rendered = transformer.render_synthetic_short_asset(candidates[0], synthetic_video_ref="synthetic.mp4")
        self.assertEqual(missing["status"], "unsupported")
        self.assertEqual(rendered["asset_type"], "short_clip")

    def test_architecture_scenarios_and_no_external_mutation_without_confirmation(self) -> None:
        creator = Playbook(
            id="creator",
            name="Creator",
            intent_id="grow_audience",
            required_capabilities=("source.youtube", "asset.transcript", "asset.clip_candidate", "channel.linkedin"),
        )
        commerce = Playbook(
            id="commerce",
            name="Commerce",
            intent_id="sell_product",
            required_capabilities=("source.written", "entity.product", "commerce.product_catalog", "outcome.sale"),
        )
        appointment = Playbook(
            id="appointment",
            name="Appointment",
            intent_id="book_meetings",
            required_capabilities=("channel.linkedin", "outcome.lead", "outcome.meeting"),
        )
        developer = Playbook(
            id="developer",
            name="Developer",
            intent_id="drive_signups",
            required_capabilities=("entity.release", "transformation.release.social", "channel.linkedin"),
        )
        self.assertIn("source.youtube", creator.required_capabilities)
        self.assertIn("outcome.sale", commerce.required_capabilities)
        self.assertIn("outcome.meeting", appointment.required_capabilities)
        self.assertIn("entity.release", developer.required_capabilities)
        item = self.content.create_written_content(workspace_id="linkedin", title="Safety", body="Ready body")
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


if __name__ == "__main__":
    unittest.main()
