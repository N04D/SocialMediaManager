from __future__ import annotations

import json

import pytest

from src.core.content.models import ContentCompleteness
from src.core.content.publications import (
    InMemoryMetricsSnapshotRepository,
    InMemoryPublicationRepository,
    PublicationGraphError,
    append_metrics_snapshot,
    reconcile_publication_for_external_content,
)
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from youtube_metrics_normalizer import (
    YOUTUBE_METRICS_NORMALIZER_ID,
    YOUTUBE_METRICS_NORMALIZER_VERSION,
    YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION,
    normalize_youtube_video_statistics,
)


def _publication():
    content_repo = InMemoryContentRepository()
    snapshot = ExternalResourceSnapshot(
        resource_ref=ResourceRef(provider="youtube", resource_type="video", external_id="vid-metrics"),
        fields={"completeness": ContentCompleteness.METADATA_ONLY.value, "title": "Metrics", "description": ""},
    )
    item, _revision, _ = content_repo.upsert_external_resource(snapshot=snapshot, provenance={"workspace_id": "ws"})
    publications = InMemoryPublicationRepository()
    publication, _ = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
    )
    return publications, publication


def _append(publications, metrics, publication, *, observed_at: str, views: int, likes: int | None = None, execution: str = "exec"):
    raw = {"statistics": {"viewCount": str(views)}}
    if likes is not None:
        raw["statistics"]["likeCount"] = str(likes)
    return append_metrics_snapshot(
        publication_repository=publications,
        metrics_repository=metrics,
        publication_id=publication.publication_id,
        observed_at=observed_at,
        provider="youtube",
        normalized_metrics=normalize_youtube_video_statistics(raw),
        raw_metrics_payload=raw,
        provider_schema_version=YOUTUBE_METRICS_PROVIDER_SCHEMA_VERSION,
        normalizer_id=YOUTUBE_METRICS_NORMALIZER_ID,
        normalizer_version=YOUTUBE_METRICS_NORMALIZER_VERSION,
        provenance={"execution_id": execution, "install_id": "yt-install"},
        provider_reporting_window={"type": "lifetime_to_date"},
        provider_observation_id=observed_at,
        collection_execution_id=execution,
    )


def test_metrics_snapshot_append_only_retry_same_values_later_and_changed_metrics():
    publications, publication = _publication()
    metrics = InMemoryMetricsSnapshotRepository()

    first, created1 = _append(publications, metrics, publication, observed_at="2026-08-10T10:00:00Z", views=100, likes=0)
    retry, created_retry = _append(publications, metrics, publication, observed_at="2026-08-10T10:00:00Z", views=100, likes=0)
    same_values_later, created2 = _append(
        publications, metrics, publication, observed_at="2026-08-10T11:00:00Z", views=100, likes=0
    )
    changed, created3 = _append(publications, metrics, publication, observed_at="2026-08-10T12:00:00Z", views=150, likes=15)

    assert created1 is True
    assert created_retry is False
    assert retry.snapshot_id == first.snapshot_id
    assert created2 is True
    assert created3 is True
    assert len(metrics.list_metrics_history(publication.publication_id)) == 3
    assert same_values_later.snapshot_id != first.snapshot_id
    assert changed.normalized_metrics["views"]["value"] == 150
    assert changed.raw_metrics_payload["statistics"]["likeCount"] == "15"
    assert metrics.get_latest_metrics(publication.publication_id).snapshot_id == changed.snapshot_id


def test_missing_values_remain_missing_zero_remains_zero_and_raw_can_renormalize():
    publications, publication = _publication()
    metrics = InMemoryMetricsSnapshotRepository()
    snapshot, _ = _append(publications, metrics, publication, observed_at="2026-08-10T10:00:00Z", views=0, likes=None)

    assert snapshot.normalized_metrics["views"]["value"] == 0
    assert "likes" not in snapshot.normalized_metrics
    renormalized = normalize_youtube_video_statistics(snapshot.raw_metrics_payload)
    assert renormalized == snapshot.normalized_metrics
    assert json.dumps(snapshot.raw_metrics_payload, sort_keys=True)


def test_metrics_require_existing_publication_and_do_not_persist_secret_canary():
    publications = InMemoryPublicationRepository()
    metrics = InMemoryMetricsSnapshotRepository()
    with pytest.raises(PublicationGraphError) as missing:
        append_metrics_snapshot(
            publication_repository=publications,
            metrics_repository=metrics,
            publication_id="missing",
            observed_at="2026-08-10T10:00:00Z",
            provider="youtube",
            normalized_metrics={},
            raw_metrics_payload={},
            provider_schema_version="schema",
            normalizer_id="norm",
            normalizer_version="1",
            provenance={},
        )
    assert missing.value.code == "PUBLICATION_NOT_FOUND"

    publications, publication = _publication()
    with pytest.raises(Exception):
        append_metrics_snapshot(
            publication_repository=publications,
            metrics_repository=metrics,
            publication_id=publication.publication_id,
            observed_at="2026-08-10T10:00:00Z",
            provider="youtube",
            normalized_metrics={},
            raw_metrics_payload={"Authorization": "Bearer SECRET_CANARY"},
            provider_schema_version="schema",
            normalizer_id="norm",
            normalizer_version="1",
            provenance={},
        )
