from __future__ import annotations

import json

import pytest

from src.core.content.artifacts import InMemoryArtifactRepository, LocalArtifactStorage
from src.core.content.models import ArtifactType, ContentCompleteness
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.content.transcripts import TranscriptArtifactIngestor, parse_vtt


VTT = """WEBVTT

00:00:01.200 --> 00:00:03.400
Hello <b>world</b>

00:00:04.000 --> 00:00:05.500
Sabr &amp; unicode: café
"""


def _video(repo: InMemoryContentRepository):
    snapshot = ExternalResourceSnapshot(
        resource_ref=ResourceRef(provider="youtube", resource_type="video", external_id="vid-60"),
        fields={
            "completeness": ContentCompleteness.METADATA_ONLY.value,
            "description": "metadata only",
            "title": "Video 60",
            "video_id": "vid-60",
        },
    )
    return repo.upsert_external_resource(snapshot=snapshot, provenance={"workspace_id": "ws", "execution_id": "exec"})


def test_vtt_parser_is_deterministic_preserves_timestamps_unicode_and_plain_text():
    first = parse_vtt(VTT, language="en")
    second = parse_vtt(VTT, language="en")

    assert first == second
    assert first.segments[0].start_ms == 1200
    assert first.segments[0].end_ms == 3400
    assert first.segments[0].text == "Hello world"
    assert "café" in first.plain_text


def test_vtt_parser_malformed_empty_and_size_limit():
    with pytest.raises(Exception) as malformed:
        parse_vtt("WEBVTT\n\nbad cue")
    assert malformed.value.code == "TRANSCRIPT_PARSE_FAILED"

    with pytest.raises(Exception) as empty:
        parse_vtt("WEBVTT\n\n")
    assert empty.value.code == "TRANSCRIPT_EMPTY"

    with pytest.raises(Exception) as too_large:
        parse_vtt(b"x" * 20, max_bytes=10)
    assert too_large.value.code == "ARTIFACT_TOO_LARGE"


def test_raw_and_normalized_artifacts_are_created_deduped_and_mark_completeness(tmp_path):
    content_repo = InMemoryContentRepository()
    item, revision, _ = _video(content_repo)
    artifact_repo = InMemoryArtifactRepository()
    ingestor = TranscriptArtifactIngestor(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        storage=LocalArtifactStorage(tmp_path),
    )

    result = ingestor.ingest_transcript(
        content_item=item,
        revision=revision,
        raw_data=VTT,
        source="youtube_official_captions",
        language="en",
        provenance={
            "provider": "youtube",
            "video_id": "vid-60",
            "caption_track_id": "cap-1",
            "source_capability": "youtube.transcript.read",
            "execution_id": "exec",
        },
        metadata={"caption_track_id": "cap-1", "track_kind": "standard"},
    )
    assert result["raw_created"] is True
    assert result["normalized_created"] is True
    assert result["raw_artifact"].artifact_type == ArtifactType.TRANSCRIPT_RAW.value
    assert result["normalized_artifact"].artifact_type == ArtifactType.TRANSCRIPT_NORMALIZED.value
    assert result["normalized_artifact"].metadata["parser_id"] == "smm.vtt.transcript"
    stored = json.loads((tmp_path / result["normalized_artifact"].storage_ref).read_text())
    assert stored["normalized_transcript"]["segments"][0]["start_ms"] == 1200
    assert content_repo.get_content_item(item.id).metadata["completeness"] == ContentCompleteness.TRANSCRIPT_AVAILABLE.value

    replay = ingestor.ingest_transcript(
        content_item=content_repo.get_content_item(item.id),
        revision=revision,
        raw_data=VTT,
        source="youtube_official_captions",
        language="en",
        provenance={"provider": "youtube", "video_id": "vid-60", "caption_track_id": "cap-1"},
        metadata={"caption_track_id": "cap-1", "track_kind": "standard"},
    )
    assert replay["raw_created"] is False
    assert replay["normalized_created"] is False
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_RAW.value)) == 1
    assert len(artifact_repo.find(content_entity_id=item.id, artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value)) == 1


def test_supplied_transcript_uses_same_pipeline_with_distinct_provenance(tmp_path):
    content_repo = InMemoryContentRepository()
    item, revision, _ = _video(content_repo)
    artifact_repo = InMemoryArtifactRepository()
    ingestor = TranscriptArtifactIngestor(
        content_repository=content_repo,
        artifact_repository=artifact_repo,
        storage=LocalArtifactStorage(tmp_path),
    )

    result = ingestor.ingest_supplied_transcript(
        content_item=item,
        revision=revision,
        transcript_vtt=VTT,
        language="en",
        supplied_by="operator",
    )

    assert result["raw_artifact"].source == "user_supplied"
    assert result["raw_artifact"].provenance["provider"] == "user_supplied"
    assert result["normalized_artifact"].metadata["generation_method"] == "user_supplied"
    assert result["raw_artifact"].provenance["provider"] != "youtube"
