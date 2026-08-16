from __future__ import annotations

from src.core.content.artifacts import InMemoryArtifactRepository, LocalArtifactStorage
from src.core.content.models import ContentCompleteness, PublicationState
from src.core.content.performance_context import (
    CONTENT_PERFORMANCE_CONTEXT_SCHEMA_VERSION,
    ContentPerformanceContextService,
)
from src.core.content.publications import (
    InMemoryMetricsSnapshotRepository,
    InMemoryPublicationRepository,
    append_metrics_snapshot,
    reconcile_publication_for_external_content,
)
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.content.transcripts import TranscriptArtifactIngestor
from youtube_metrics_normalizer import (
    YOUTUBE_METRICS_NORMALIZER_ID,
    YOUTUBE_METRICS_NORMALIZER_VERSION,
    YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION,
    normalize_youtube_video_statistics,
)


def _build_context_fixture(tmp_path):
    content_repo = InMemoryContentRepository()
    artifact_repo = InMemoryArtifactRepository()
    publication_repo = InMemoryPublicationRepository()
    metrics_repo = InMemoryMetricsSnapshotRepository()

    snapshot = ExternalResourceSnapshot(
        resource_ref=ResourceRef(
            provider="youtube",
            resource_type="video",
            external_id="phase62-video",
            install_id="yt-install",
        ),
        fields={
            "completeness": ContentCompleteness.METADATA_ONLY.value,
            "description": "Read-only context proof",
            "published_at": "2026-08-11T09:00:00Z",
            "title": "Phase 62",
            "video_id": "phase62-video",
        },
    )
    item, revision, _ = content_repo.upsert_external_resource(
        snapshot=snapshot,
        provenance={"workspace_id": "ws", "source_event_id": "evt-62", "execution_id": "exec-video-read"},
    )
    TranscriptArtifactIngestor(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        storage=LocalArtifactStorage(tmp_path),
    ).ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data="WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nSECRET_CANARY transcript body\n",
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-62", "execution_id": "exec-transcript"},
        metadata={"caption_track_id": "cap-62", "track_kind": "standard"},
    )
    youtube_publication, _ = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publication_repo,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
        state=PublicationState.PUBLISHED.value,
        provenance={"source_event_id": "evt-62", "source_execution_id": "exec-video-read"},
    )
    website_publication, _ = publication_repo.save(
        youtube_publication.__class__(
            publication_id="publication_website_phase62",
            content_entity_id=item.id,
            content_revision_id=revision.id,
            provider="website",
            install_id="website-install",
            external_ref={
                "provider": "website",
                "resource_type": "article",
                "external_id": "phase62-article",
                "canonical_ref": "website:article:phase62-article",
            },
            published_at="2026-08-12T09:00:00Z",
            observed_at="2026-08-12T09:05:00Z",
            state=PublicationState.PUBLISHED.value,
            provenance={"execution_id": "exec-website"},
            metadata={"route": "article"},
        )
    )
    for observed_at, views, execution_id in (
        ("2026-08-11T10:00:00Z", 100, "metrics-1"),
        ("2026-08-11T11:00:00Z", 100, "metrics-2"),
        ("2026-08-11T12:00:00Z", 150, "metrics-3"),
    ):
        raw = {"statistics": {"likeCount": "5", "viewCount": str(views)}, "debug_canary": "SECRET_CANARY"}
        append_metrics_snapshot(
            publication_repository=publication_repo,
            metrics_repository=metrics_repo,
            publication_id=youtube_publication.publication_id,
            observed_at=observed_at,
            provider="youtube",
            normalized_metrics=normalize_youtube_video_statistics(raw),
            raw_metrics_payload=raw,
            provider_schema_version=YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION,
            normalizer_id=YOUTUBE_METRICS_NORMALIZER_ID,
            normalizer_version=YOUTUBE_METRICS_NORMALIZER_VERSION,
            provenance={"execution_id": execution_id, "install_id": "yt-install"},
            provider_reporting_window={"period_start": "2026-08-11", "period_end": "2026-08-11"},
            provider_observation_id=observed_at,
            collection_execution_id=execution_id,
        )
    append_metrics_snapshot(
        publication_repository=publication_repo,
        metrics_repository=metrics_repo,
        publication_id=website_publication.publication_id,
        observed_at="2026-08-12T10:00:00Z",
        provider="website",
        normalized_metrics={
            "views": {
                "metric_key": "views",
                "value": 12,
                "unit": "count",
                "value_type": "integer",
                "provider_source_field": "views",
                "metadata": {},
            }
        },
        raw_metrics_payload={"views": 12},
        provider_schema_version="website-local-v1",
        normalizer_id="website.metrics.normalizer",
        normalizer_version="0.1.0",
        provenance={"execution_id": "website-metrics"},
        provider_observation_id="2026-08-12T10:00:00Z",
        collection_execution_id="website-metrics",
    )
    service = ContentPerformanceContextService(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        publication_repository=publication_repo,
        metrics_repository=metrics_repo,
        clock=lambda: "2026-08-16T00:00:00Z",
    )
    return item, service, youtube_publication


def test_context_constructs_content_transcript_publications_metrics_and_provenance(tmp_path):
    item, service, youtube_publication = _build_context_fixture(tmp_path)

    context = service.get_context(item.id)
    payload = context.to_dict()

    assert payload["schema_version"] == CONTENT_PERFORMANCE_CONTEXT_SCHEMA_VERSION
    assert payload["content_entity"]["content_entity_id"] == item.id
    assert payload["current_revision"]["content_revision_id"] == item.current_revision_id
    assert payload["transcript_state"]["available"] is True
    assert payload["transcript_state"]["normalized_artifact_id"].startswith("artifact_")
    assert payload["transcript_state"]["language"] == "en"
    assert payload["transcript_state"]["parser_id"] == "smm.vtt.transcript"
    assert payload["transcript_state"]["completeness_level"] == ContentCompleteness.TRANSCRIPT_AVAILABLE.value
    assert [publication["provider"] for publication in payload["publications"]] == ["website", "youtube"]
    youtube_context = [pub for pub in payload["publications"] if pub["publication_id"] == youtube_publication.publication_id][0]
    assert len(youtube_context["metrics_history"]) == 3
    assert youtube_context["metrics_history"][0]["normalized_metrics"]["views"]["value"] == 100
    assert youtube_context["metrics_history"][1]["normalized_metrics"]["views"]["value"] == 100
    assert youtube_context["metrics_history"][2]["normalized_metrics"]["views"]["value"] == 150
    assert payload["freshness"] == {
        "latest_metrics_observed_at": "2026-08-12T10:00:00Z",
        "metrics_present": True,
        "publication_count": 2,
        "snapshot_count": 4,
    }
    assert payload["provenance"]["content_entity_id"] == item.id


def test_context_by_external_ref_and_deterministic_output(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    external_ref = dict(item.metadata["external_ref"])

    first = service.get_context_by_external_ref(
        provider="youtube",
        install_id="yt-install",
        external_ref=external_ref,
    ).to_dict()
    second = service.get_context(item.id).to_dict()

    assert first == second
