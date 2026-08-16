from __future__ import annotations

from src.core.content.artifacts import InMemoryArtifactRepository, LocalArtifactStorage
from src.core.content.models import ArtifactType, ContentCompleteness
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.content.transcripts import TranscriptArtifactIngestor


VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello recovery\n"
VTT_UPDATED = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello updated\n"


def _stack(tmp_path):
    content_repo = InMemoryContentRepository()
    snapshot = ExternalResourceSnapshot(
        resource_ref=ResourceRef(provider="youtube", resource_type="video", external_id="vid-rec"),
        fields={"completeness": ContentCompleteness.METADATA_ONLY.value, "title": "Recovery", "description": ""},
    )
    item, revision, _ = content_repo.upsert_external_resource(snapshot=snapshot, provenance={"workspace_id": "ws"})
    artifact_repo = InMemoryArtifactRepository()
    ingestor = TranscriptArtifactIngestor(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        storage=LocalArtifactStorage(tmp_path),
    )
    return content_repo, artifact_repo, ingestor, item, revision


def test_crash_after_raw_reuses_raw_and_converges(tmp_path):
    content_repo, artifact_repo, ingestor, item, revision = _stack(tmp_path)
    raw, created = ingestor.ingest_raw_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT,
        media_type="text/vtt",
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-1"},
        metadata={"caption_track_id": "cap-1"},
    )
    assert created is True
    assert content_repo.get_content_item(item.id).metadata["completeness"] == ContentCompleteness.METADATA_ONLY.value

    normalized, normalized_created, _ = ingestor.normalize_raw_artifact(raw)
    ingestor.mark_transcript_available(item, normalized)
    assert normalized_created is True
    assert content_repo.get_content_item(item.id).metadata["completeness"] == ContentCompleteness.TRANSCRIPT_AVAILABLE.value
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_RAW.value)) == 1


def test_crash_after_normalization_reconciliation_restores_completeness(tmp_path):
    content_repo, artifact_repo, ingestor, item, revision = _stack(tmp_path)
    raw, _ = ingestor.ingest_raw_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT,
        media_type="text/vtt",
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-1"},
        metadata={"caption_track_id": "cap-1"},
    )
    ingestor.normalize_raw_artifact(raw)
    assert content_repo.get_content_item(item.id).metadata["completeness"] == ContentCompleteness.METADATA_ONLY.value

    ingestor.reconcile_transcript_availability(item)
    assert content_repo.get_content_item(item.id).metadata["completeness"] == ContentCompleteness.TRANSCRIPT_AVAILABLE.value
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value)) == 1


def test_updated_and_replacement_tracks_preserve_history(tmp_path):
    _, artifact_repo, ingestor, item, revision = _stack(tmp_path)
    first = ingestor.ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT,
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-1", "provider_last_updated": "T1"},
        metadata={"caption_track_id": "cap-1", "track_kind": "standard"},
    )
    updated = ingestor.ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT_UPDATED,
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-1", "provider_last_updated": "T2"},
        metadata={"caption_track_id": "cap-1", "track_kind": "standard"},
    )
    replacement = ingestor.ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT_UPDATED,
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "caption_track_id": "cap-2", "provider_last_updated": "T3"},
        metadata={"caption_track_id": "cap-2", "track_kind": "standard"},
    )

    assert first["raw_artifact"].artifact_id != updated["raw_artifact"].artifact_id
    assert replacement["raw_artifact"].provenance["caption_track_id"] == "cap-2"
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_RAW.value)) == 3
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value)) == 3
