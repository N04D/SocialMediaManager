from __future__ import annotations

import json

from src.core.content.artifacts import InMemoryArtifactRepository, LocalArtifactStorage
from src.core.content.models import ArtifactType, ContentCompleteness
from src.core.content.publications import (
    ContentPerformanceQueryService,
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


VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nGraph proof\n"


def test_youtube_end_to_end_content_transcript_publication_metrics_graph(tmp_path):
    content_repo = InMemoryContentRepository()
    artifact_repo = InMemoryArtifactRepository()
    publication_repo = InMemoryPublicationRepository()
    metrics_repo = InMemoryMetricsSnapshotRepository()

    external_snapshot = ExternalResourceSnapshot(
        resource_ref=ResourceRef(provider="youtube", resource_type="video", external_id="vid-graph", install_id="yt"),
        fields={
            "completeness": ContentCompleteness.METADATA_ONLY.value,
            "description": "Graph video",
            "published_at": "2026-08-10T00:00:00Z",
            "title": "Graph",
            "video_id": "vid-graph",
        },
    )
    item, revision, _ = content_repo.upsert_external_resource(
        snapshot=external_snapshot,
        provenance={"workspace_id": "ws", "source_event_id": "evt-yt", "execution_id": "exec-read"},
    )
    transcript_result = TranscriptArtifactIngestor(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        storage=LocalArtifactStorage(tmp_path),
    ).ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT,
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-graph", "execution_id": "exec-transcript"},
        metadata={"caption_track_id": "cap-graph", "track_kind": "standard"},
    )
    content_with_transcript = content_repo.get_content_item(item.id)
    publication, publication_created = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publication_repo,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
        provenance={"source_event_id": "evt-yt", "source_execution_id": "exec-read"},
    )

    for observed_at, views in (("2026-08-10T10:00:00Z", 100), ("2026-08-10T14:00:00Z", 150)):
        raw = {"statistics": {"viewCount": str(views), "likeCount": "10"}}
        append_metrics_snapshot(
            publication_repository=publication_repo,
            metrics_repository=metrics_repo,
            publication_id=publication.publication_id,
            observed_at=observed_at,
            provider="youtube",
            normalized_metrics=normalize_youtube_video_statistics(raw),
            raw_metrics_payload=raw,
            provider_schema_version=YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION,
            normalizer_id=YOUTUBE_METRICS_NORMALIZER_ID,
            normalizer_version=YOUTUBE_METRICS_NORMALIZER_VERSION,
            provenance={"execution_id": f"metrics-{views}", "install_id": "yt-install"},
            provider_observation_id=observed_at,
            collection_execution_id=f"metrics-{views}",
        )

    graph = ContentPerformanceQueryService(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        publication_repository=publication_repo,
        metrics_repository=metrics_repo,
    ).content_performance_graph(item.id)

    assert len(content_repo.items) == 1
    assert publication_created is True
    assert len(publication_repo.list_by_content(item.id)) == 1
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value)) == 1
    assert len(metrics_repo.list_metrics_history(publication.publication_id)) == 2
    assert content_with_transcript.metadata["completeness"] == ContentCompleteness.TRANSCRIPT_AVAILABLE.value
    assert transcript_result["normalized_artifact"].content_entity_id == publication.content_entity_id == item.id
    assert graph["content_entity_id"] == item.id
    assert graph["transcript"]["available"] is True
    assert graph["publications"][0]["publication_id"] == publication.publication_id
    assert len(graph["publications"][0]["metrics"]) == 2
    assert "raw_metrics_payload" not in json.dumps(graph)
    assert graph["publications"][0]["metrics"][0]["provenance"]["content_entity_id"] == item.id


def test_generic_core_has_no_provider_specific_branches():
    import inspect
    import src.core.content.publications as publications

    source = inspect.getsource(publications)
    assert 'if provider == "youtube"' not in source
    assert 'if publication.provider == "youtube"' not in source
