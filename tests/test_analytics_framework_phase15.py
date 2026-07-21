from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import channel_store
from analytics_mcp import (
    analytics_compare_revisions,
    analytics_get_content_performance,
    analytics_get_publication_performance,
    analytics_list_metrics,
)
from analytics_services import (
    AnalyticsValidationError,
    MetricDefinitionRegistry,
    attribution_checksum,
    compute_deltas,
    observation_key,
)
from channel_models import ContentDerivative, PostMetricSnapshot, PublishedPost, PublishJob
from channel_store import save_derivative, save_metric_snapshot, save_publish_job, save_published_post
from channels.linkedin.metric_definitions import register_linkedin_metric_definitions
from src.core.analytics import (
    ANALYTICS_FRAMEWORK_VERSION,
    ANALYTICS_INGESTION_CONTRACT_VERSION,
    ANALYTICS_READ_MODEL_CONTRACT_VERSION,
    DERIVED_METRIC_CONTRACT_VERSION,
    METRIC_DEFINITION_CONTRACT_VERSION,
    METRIC_OBSERVATION_CONTRACT_VERSION,
    PUBLICATION_ATTRIBUTION_CONTRACT_VERSION,
    ChannelMetricObservationInput,
    MetricDefinition,
    MetricObservationStatus,
    MetricSemanticType,
)
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class AnalyticsFrameworkPhase15Tests(unittest.TestCase):
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
        self.bundle = self.runtime.analytics_bundle(self.config)
        self.ingestion = self.bundle.ingestion_service
        self.readmodels = self.bundle.read_model_service
        self.attribution = self.bundle.attribution_service

    def published_post(self, *, publication_id: str = "published-1", remote_id: str = "urn:li:activity:1"):
        derivative = save_derivative(
            ContentDerivative(
                id=f"derivative-{publication_id}",
                source_document_id="content-1",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="Do not duplicate full body",
                body="Canonical publication body stays outside analytics observations.",
                status="published",
                generation_metadata_json={
                    "content_item_id": "content-1",
                    "content_revision_id": "revision-1",
                    "revision_checksum": "a" * 64,
                    "channel_variant_id": "variant-1",
                    "variant_checksum": "b" * 64,
                    "publication_plan_id": "plan-1",
                    "publication_target_id": "target-1",
                    "media_relation_ids": ["relation-1"],
                    "media_asset_ids": ["asset-1"],
                    "media_variant_ids": ["variant-media-1"],
                    "snapshot_checksum": "c" * 64,
                    "content_requirement_version": "1.0",
                    "media_requirement_version": "1.0",
                },
            )
        )
        job = save_publish_job(
            PublishJob(
                id=f"job-{publication_id}",
                derivative_id=derivative.id,
                channel_id="linkedin",
                status="success",
                requested_at="2026-07-21T08:00:00+00:00",
                finished_at="2026-07-21T08:01:00+00:00",
                result_external_id=remote_id,
                result_details_json={
                    "content_publication_evidence": {
                        "content_item_id": "content-1",
                        "content_revision_id": "revision-1",
                        "revision_checksum": "a" * 64,
                        "channel_variant_id": "variant-1",
                        "variant_checksum": "b" * 64,
                        "publication_plan_id": "plan-1",
                        "publication_target_id": "target-1",
                        "media_relation_ids": ["relation-1"],
                        "source_asset_ids": ["asset-1"],
                        "media_variant_ids": ["variant-media-1"],
                        "snapshot_checksum": "c" * 64,
                        "content_requirement_version": "1.0",
                        "media_requirement_version": "1.0",
                    }
                },
            )
        )
        return save_published_post(
            PublishedPost(
                id=publication_id,
                derivative_id=derivative.id,
                source_document_id="content-1",
                channel_id="linkedin",
                external_id=remote_id,
                external_url="https://www.linkedin.com/feed/update/urn:li:activity:1",
                published_at="2026-07-21T08:01:00+00:00",
                publish_job_id=job.id,
                status="confirmed",
                created_at="2026-07-21T08:01:00+00:00",
                updated_at="2026-07-21T08:01:00+00:00",
            )
        )

    def ingest_values(self, post: PublishedPost, *, observed_at: str, impressions: int, reactions: int = 0):
        snapshot = save_metric_snapshot(
            PostMetricSnapshot(
                id=f"snapshot-{observed_at}",
                published_post_id=post.id,
                channel_id="linkedin",
                captured_at=observed_at,
                impressions=impressions,
                reactions=reactions,
                comments=2,
                reposts=1,
                shares=1,
                clicks=3,
                raw_metrics_json={"screenshot_path": "/tmp/not-exposed.png"},
                screenshot_path="/tmp/not-exposed.png",
                created_at=observed_at,
            )
        )
        return self.ingestion.ingest_metric_snapshot(
            snapshot=snapshot,
            published_post=post,
            source_run_id=f"run-{snapshot.id}",
        )

    def test_contract_versions_health_and_linkedin_definitions(self) -> None:
        self.assertEqual(ANALYTICS_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(METRIC_DEFINITION_CONTRACT_VERSION, "1.0")
        self.assertEqual(METRIC_OBSERVATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(PUBLICATION_ATTRIBUTION_CONTRACT_VERSION, "1.0")
        self.assertEqual(DERIVED_METRIC_CONTRACT_VERSION, "1.0")
        self.assertEqual(ANALYTICS_READ_MODEL_CONTRACT_VERSION, "1.0")
        self.assertEqual(ANALYTICS_INGESTION_CONTRACT_VERSION, "1.0")
        definitions = self.bundle.metric_registry.list_definitions("channel.linkedin")
        self.assertEqual(
            {item.metric_key for item in definitions},
            {"impressions", "views", "reactions", "comments", "reposts", "shares", "clicks"},
        )
        self.assertEqual(self.bundle.health_check()["status"], "ready")

    def test_metric_definition_conflicts_and_semantics(self) -> None:
        registry = MetricDefinitionRegistry()
        register_linkedin_metric_definitions(registry)
        definition = registry.latest("channel.linkedin", "impressions")
        assert definition is not None
        registry.register(definition)
        conflicting = MetricDefinition(**{**asdict(definition), "semantic_type": MetricSemanticType.REACH.value})
        with self.assertRaises(AnalyticsValidationError):
            registry.register(conflicting)
        self.assertTrue(definition.cumulative)
        self.assertEqual(definition.aggregation_type, "latest")
        self.assertEqual(definition.comparable_group, "exposure_count")

    def test_observations_are_immutable_deduplicated_and_validated(self) -> None:
        post = self.published_post()
        first = self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=10, reactions=2)
        duplicate = self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=10, reactions=2)
        second = self.ingest_values(post, observed_at="2026-07-21T10:00:00+00:00", impressions=15, reactions=4)
        self.assertGreater(first["run"]["observation_count"], 0)
        self.assertGreater(duplicate["run"]["duplicate_count"], 0)
        self.assertGreater(second["run"]["observation_count"], 0)
        observed = self.bundle.observation_repository.list_by_publication(post.id)
        self.assertEqual(len({item.observation_key for item in observed}), len(observed))
        key = observation_key(
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            channel_account_id="linkedin",
            remote_publication_id=post.external_id,
            metric_definition_id="channel.linkedin.impressions.v1",
            metric_definition_version="1.0",
            observed_at="2026-07-21T09:00:00+00:00",
            window_start=post.published_at,
            window_end="2026-07-21T09:00:00+00:00",
            source_run_id="run-snapshot-2026-07-21T09:00:00+00:00",
            observed_value=10,
        )
        self.assertEqual(len(key), 64)
        with self.assertRaises(AnalyticsValidationError):
            self.ingestion._ingest_one(
                workspace_id="linkedin",
                channel_plugin_id="channel.linkedin",
                channel_account_id="wrong",
                item=ChannelMetricObservationInput(
                    remote_publication_id=post.external_id,
                    publication_id=post.id,
                    metric_key="impressions",
                    value=1,
                    observed_at="2026-07-21T11:00:00+00:00",
                ),
                source_type="test",
                source_run_id="wrong",
            )

    def test_publication_attribution_is_historical_and_checksumed(self) -> None:
        post = self.published_post()
        attribution = self.attribution.resolve_publication(post.id, workspace_id="linkedin")
        self.assertEqual(attribution.status, "complete")
        self.assertEqual(attribution.content_revision_id, "revision-1")
        self.assertEqual(attribution.channel_variant_id, "variant-1")
        self.assertEqual(attribution.media_asset_ids, ["asset-1"])
        self.assertEqual(attribution.attribution_checksum, attribution_checksum(attribution))
        derivative = channel_store.get_derivative(post.derivative_id)
        assert derivative is not None
        derivative.generation_metadata_json["content_revision_id"] = "revision-2"
        save_derivative(derivative)
        self.assertEqual(self.attribution.resolve_publication(post.id).content_revision_id, "revision-1")

    def test_partial_backfill_is_bounded_and_dry_run(self) -> None:
        self.published_post(publication_id="legacy", remote_id="urn:li:activity:legacy")
        result = self.attribution.backfill(workspace_id="linkedin", batch_size=1, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(self.bundle.attribution_repository.list_all(workspace_id="linkedin"), [])

    def test_corrections_are_traceable_and_cycles_blocked(self) -> None:
        post = self.published_post()
        self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=10)
        observation = next(
            item
            for item in self.bundle.observation_repository.list_by_publication(post.id)
            if item.metric_key == "impressions"
        )
        correction = self.ingestion.correct_observation(
            observation.id,
            corrected_value=11,
            actor="tester",
            reason_code="scrape_fix",
            reason="Corrected visible count.",
        )
        self.assertTrue(correction.corrected_observation_id)
        original = self.bundle.observation_repository.get(observation.id)
        assert original is not None
        self.assertEqual(original.status, MetricObservationStatus.CORRECTED.value)
        with self.assertRaises(AnalyticsValidationError):
            self.ingestion.correct_observation(
                correction.corrected_observation_id,
                corrected_value=12,
                actor="tester",
                reason_code="cycle",
                reason="Cycle attempt.",
            )

    def test_cumulative_deltas_and_derived_rates_are_safe(self) -> None:
        post = self.published_post()
        self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=20, reactions=2)
        self.ingest_values(post, observed_at="2026-07-21T10:00:00+00:00", impressions=15, reactions=3)
        observations = self.bundle.observation_repository.list_by_publication(post.id)
        deltas, warnings = compute_deltas(observations, self.bundle.metric_registry)
        self.assertIsNone(deltas["impressions"]["value"])
        self.assertIn("impressions:cumulative_regression", warnings)
        latest = self.readmodels.publication_performance(post.id)["latest_metrics"]
        derived, derived_warnings = self.readmodels.compute_derived(latest)
        self.assertIsNotNone(derived["engagement_rate_by_impressions"]["value"])
        self.assertIsNone(derived["engagement_rate_by_reach"]["value"])
        self.assertIn("engagement_rate_by_reach:missing_or_zero_denominator", derived_warnings)

    def test_readmodels_keep_context_without_content_or_paths(self) -> None:
        post = self.published_post()
        self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=20, reactions=2)
        publication = self.readmodels.publication_performance(post.id)
        self.assertEqual(publication["revision_id"], "revision-1")
        self.assertEqual(publication["media_asset_ids"], ["asset-1"])
        self.assertIn("freshness", publication)
        self.assertIn("completeness", publication)
        content = self.readmodels.content_performance("content-1", workspace_id="linkedin")
        media = self.readmodels.media_performance("asset-1", workspace_id="linkedin")
        campaign = self.readmodels.campaign_performance("", workspace_id="linkedin")
        serialized = json.dumps(publication | content | media | campaign)
        self.assertNotIn("Canonical publication body", serialized)
        self.assertNotIn("storage_reference", serialized)
        self.assertNotIn("/tmp/not-exposed", serialized)
        self.assertIn("publication_included_asset", media["attribution_note"])
        self.assertIn("observational_not_causal", content["warnings"])

    def test_comparisons_and_mcp_are_read_only_and_contextual(self) -> None:
        post = self.published_post()
        self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=20, reactions=2)
        metrics = analytics_list_metrics(self.runtime, self.config, channel_plugin_id="channel.linkedin")
        publication = analytics_get_publication_performance(self.runtime, self.config, post.id)
        content = analytics_get_content_performance(self.runtime, self.config, "content-1", workspace_id="linkedin")
        revisions = analytics_compare_revisions(self.runtime, self.config, "content-1", workspace_id="linkedin")
        self.assertTrue(metrics["read_only"])
        self.assertTrue(publication["read_only"])
        self.assertTrue(content["read_only"])
        self.assertTrue(revisions["read_only"])
        self.assertIn("definition_versions", metrics)
        self.assertIn("completeness", publication)
        self.assertIn("freshness", content)

    def test_linkedin_integration_boundaries_and_dashboard_surface(self) -> None:
        metrics_source = Path("channels/linkedin/worker/metrics.py").read_text(encoding="utf-8")
        self.assertIn("analytics_ingestion_service", metrics_source)
        self.assertNotIn("ObservationRepository", metrics_source)
        self.assertNotIn("AttributionRepository", metrics_source)
        analytics_source = Path("analytics_services.py").read_text(encoding="utf-8")
        dashboard_source = Path("dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn("channels.linkedin", analytics_source)
        self.assertNotIn("create_session(", analytics_source)
        self.assertIn("ROUTE_ANALYTICS", dashboard_source)
        self.assertIn("/api/analytics/health", dashboard_source)
        self.assertNotIn("providersecret", dashboard_source.lower())

    def test_integrity_detects_safe_issues_and_rebuilds_snapshot(self) -> None:
        post = self.published_post()
        self.ingest_values(post, observed_at="2026-07-21T09:00:00+00:00", impressions=20)
        issues = self.bundle.integrity_service.scan(workspace_id="linkedin")
        self.assertIsInstance(issues, list)
        snapshot = self.readmodels.rebuild_read_model(
            read_model_type="publication",
            subject_id=post.id,
            workspace_id="linkedin",
        )
        self.assertEqual(snapshot.read_model_type, "publication")
        self.assertTrue(snapshot.source_observation_watermark)
