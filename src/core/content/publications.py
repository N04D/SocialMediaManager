from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from src.core.content.artifacts import ArtifactRepository
from src.core.content.models import ArtifactType, MetricsSnapshot, NormalizedMetricValue, Publication, PublicationState
from src.core.content.repository import ContentRepository
from src.core.content.resources import ResourceRef
from src.core.runtime.events import utc_now_iso
from src.core.runtime.execution_context import _assert_no_secret_values

_BLOCKED_CREDENTIAL_FRAGMENTS = ("password", "token", "secret", "credential", "api_key", "authorization")


class PublicationGraphError(Exception):
    def __init__(self, code: str, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _assert_no_credentials(value: Any, *, code: str) -> None:
    _assert_no_secret_values(value, code=code)
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _BLOCKED_CREDENTIAL_FRAGMENTS) and not lowered.endswith("_ref"):
                raise PublicationGraphError(code, "Publication graph payload must not contain credential-shaped fields.")
            _assert_no_credentials(child, code=code)
    elif isinstance(value, list):
        for item in value:
            _assert_no_credentials(item, code=code)
    elif isinstance(value, str) and value.lower().startswith("bearer "):
        raise PublicationGraphError(code, "Publication graph payload must not contain bearer credentials.")


def publication_identity(*, provider: str, install_id: str, external_ref: dict[str, Any]) -> str:
    payload = {
        "external_ref": {
            "canonical_ref": str(external_ref.get("canonical_ref") or ""),
            "external_id": str(external_ref.get("external_id") or ""),
            "resource_type": str(external_ref.get("resource_type") or ""),
        },
        "install_id": install_id,
        "provider": provider,
    }
    return f"publication_{_digest(payload)[:32]}"


def metrics_snapshot_identity(
    *,
    publication_id: str,
    observed_at: str,
    provider_observation_id: str = "",
    collection_execution_id: str = "",
) -> str:
    payload = {
        'collection_execution_id': collection_execution_id,
        'observed_at': observed_at,
        'provider_observation_id': provider_observation_id,
        'publication_id': publication_id,
    }
    return f"metrics_snapshot_{_digest(payload)[:32]}"


def normalized_metric(
    metric_key: str,
    value: int | str | bool,
    *,
    unit: str = "count",
    value_type: str = "integer",
    provider_source_field: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asdict(
        NormalizedMetricValue(
            metric_key=metric_key,
            value=value,
            unit=unit,
            value_type=value_type,
            provider_source_field=provider_source_field,
            metadata=dict(metadata or {}),
        )
    )


class PublicationRepository(Protocol):
    def save(self, publication: Publication) -> tuple[Publication, bool]: ...

    def get(self, publication_id: str) -> Publication | None: ...

    def get_by_identity(self, *, provider: str, install_id: str, external_ref: dict[str, Any]) -> Publication | None: ...

    def list_by_content(self, content_entity_id: str) -> tuple[Publication, ...]: ...


@dataclass
class InMemoryPublicationRepository:
    publications: dict[str, Publication] = field(default_factory=dict)

    def save(self, publication: Publication) -> tuple[Publication, bool]:
        _assert_no_credentials(asdict(publication), code="publication.secret_value")
        existing = self.publications.get(publication.publication_id)
        if existing:
            merged = Publication(
                **{
                    **existing.__dict__,
                    "content_revision_id": publication.content_revision_id or existing.content_revision_id,
                    "observed_at": publication.observed_at or existing.observed_at,
                    "published_at": publication.published_at or existing.published_at,
                    "state": publication.state or existing.state,
                    "provenance": {**existing.provenance, **publication.provenance},
                    "metadata": {**existing.metadata, **publication.metadata},
                }
            )
            self.publications[merged.publication_id] = merged
            return merged, False
        self.publications[publication.publication_id] = publication
        return publication, True

    def get(self, publication_id: str) -> Publication | None:
        return self.publications.get(publication_id)

    def get_by_identity(self, *, provider: str, install_id: str, external_ref: dict[str, Any]) -> Publication | None:
        return self.get(publication_identity(provider=provider, install_id=install_id, external_ref=external_ref))

    def list_by_content(self, content_entity_id: str) -> tuple[Publication, ...]:
        return tuple(
            sorted(
                (item for item in self.publications.values() if item.content_entity_id == content_entity_id),
                key=lambda item: (item.provider, item.install_id, item.publication_id),
            )
        )


@dataclass
class InMemoryMetricsSnapshotRepository:
    snapshots: dict[str, MetricsSnapshot] = field(default_factory=dict)

    def append(self, snapshot: MetricsSnapshot) -> tuple[MetricsSnapshot, bool]:
        _assert_no_credentials(asdict(snapshot), code="metrics_snapshot.secret_value")
        existing = self.snapshots.get(snapshot.snapshot_id)
        if existing:
            return existing, False
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot, True

    def get(self, snapshot_id: str) -> MetricsSnapshot | None:
        return self.snapshots.get(snapshot_id)

    def list_metrics_history(self, publication_id: str) -> tuple[MetricsSnapshot, ...]:
        return tuple(
            sorted(
                (item for item in self.snapshots.values() if item.publication_id == publication_id),
                key=lambda item: (item.observed_at, item.snapshot_id),
            )
        )

    def get_latest_metrics(self, publication_id: str) -> MetricsSnapshot | None:
        history = self.list_metrics_history(publication_id)
        return history[-1] if history else None


def reconcile_publication_for_external_content(
    *,
    content_repository: ContentRepository,
    publication_repository: PublicationRepository,
    canonical_ref: str,
    install_id: str,
    content_revision_id: str = "",
    state: str = PublicationState.PUBLISHED.value,
    provenance: dict[str, Any] | None = None,
) -> tuple[Publication, bool]:
    item = content_repository.get_by_external_ref(canonical_ref)
    if item is None:
        raise PublicationGraphError("CONTENT_ENTITY_NOT_FOUND", "Content entity was not found for external ref.")
    external_ref = dict(item.metadata.get("external_ref") or {})
    if not external_ref:
        external_ref = ResourceRef(
            provider=item.primary_source_type,
            resource_type="resource",
            external_id=item.primary_source_entity_id,
            install_id=install_id,
            canonical_ref=canonical_ref,
        ).to_dict()
    revision_id = content_revision_id or item.current_revision_id
    publication = Publication(
        publication_id=publication_identity(
            provider=str(external_ref.get("provider") or item.primary_source_type),
            install_id=install_id,
            external_ref=external_ref,
        ),
        content_entity_id=item.id,
        content_revision_id=revision_id,
        provider=str(external_ref.get("provider") or item.primary_source_type),
        install_id=install_id,
        external_ref=external_ref,
        published_at=str(item.primary_source_metadata.get("published_at") or ""),
        observed_at=utc_now_iso(),
        state=state,
        provenance={
            "content_entity_id": item.id,
            "content_revision_id": revision_id,
            "external_ref": external_ref,
            **dict(provenance or {}),
        },
        metadata={"source_completeness": item.metadata.get("completeness", "")},
    )
    return publication_repository.save(publication)


def append_metrics_snapshot(
    *,
    publication_repository: PublicationRepository,
    metrics_repository: InMemoryMetricsSnapshotRepository,
    publication_id: str,
    observed_at: str,
    provider: str,
    normalized_metrics: dict[str, dict[str, Any]],
    raw_metrics_payload: dict[str, Any],
    provider_schema_version: str,
    normalizer_id: str,
    normalizer_version: str,
    provenance: dict[str, Any],
    provider_reporting_window: dict[str, Any] | None = None,
    provider_observation_id: str = "",
    collection_execution_id: str = "",
    raw_metrics_ref: str = "",
) -> tuple[MetricsSnapshot, bool]:
    publication = publication_repository.get(publication_id)
    if publication is None:
        raise PublicationGraphError("PUBLICATION_NOT_FOUND", "Metrics snapshot requires an existing publication.")
    _assert_no_credentials(raw_metrics_payload, code="metrics_snapshot.secret_value")
    _assert_no_credentials(provenance, code="metrics_snapshot.secret_value")
    snapshot = MetricsSnapshot(
        snapshot_id=metrics_snapshot_identity(
            publication_id=publication_id,
            observed_at=observed_at,
            provider_observation_id=provider_observation_id,
            collection_execution_id=collection_execution_id,
        ),
        publication_id=publication_id,
        observed_at=observed_at,
        provider=provider,
        normalized_metrics=dict(normalized_metrics),
        raw_metrics_payload=dict(raw_metrics_payload),
        provider_schema_version=provider_schema_version,
        normalizer_id=normalizer_id,
        normalizer_version=normalizer_version,
        provenance={
            "publication_id": publication_id,
            "content_entity_id": publication.content_entity_id,
            "content_revision_id": publication.content_revision_id,
            **dict(provenance),
        },
        provider_reporting_window=dict(provider_reporting_window or {}),
        raw_metrics_ref=raw_metrics_ref,
        created_at=utc_now_iso(),
    )
    return metrics_repository.append(snapshot)


class ContentPerformanceQueryService:
    def __init__(
        self,
        *,
        content_repository: ContentRepository,
        artifact_repository: ArtifactRepository,
        publication_repository: PublicationRepository,
        metrics_repository: InMemoryMetricsSnapshotRepository,
    ):
        self.content_repository = content_repository
        self.artifact_repository = artifact_repository
        self.publication_repository = publication_repository
        self.metrics_repository = metrics_repository

    def content_performance_graph(self, content_entity_id: str) -> dict[str, Any]:
        item = self.content_repository.get_content_item(content_entity_id)
        if item is None:
            raise PublicationGraphError("CONTENT_ENTITY_NOT_FOUND", "Content entity was not found.")
        revisions = self.content_repository.list_revisions(content_entity_id)
        current_revision = next((rev for rev in revisions if rev.id == item.current_revision_id), revisions[-1] if revisions else None)
        transcripts = self.artifact_repository.find(
            content_entity_id=content_entity_id,
            artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value,
        )
        current_transcript = transcripts[-1] if transcripts else None
        publications = []
        for publication in self.publication_repository.list_by_content(content_entity_id):
            history = self.metrics_repository.list_metrics_history(publication.publication_id)
            publications.append(
                {
                    "publication_id": publication.publication_id,
                    "content_entity_id": publication.content_entity_id,
                    "content_revision_id": publication.content_revision_id,
                    "provider": publication.provider,
                    "install_id": publication.install_id,
                    "external_ref": dict(publication.external_ref),
                    "published_at": publication.published_at,
                    "observed_at": publication.observed_at,
                    "state": publication.state,
                    "provenance": dict(publication.provenance),
                    "metrics": [
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "publication_id": snapshot.publication_id,
                            "observed_at": snapshot.observed_at,
                            "provider": snapshot.provider,
                            "normalized_metrics": dict(snapshot.normalized_metrics),
                            "provider_schema_version": snapshot.provider_schema_version,
                            "normalizer_id": snapshot.normalizer_id,
                            "normalizer_version": snapshot.normalizer_version,
                            "provider_reporting_window": dict(snapshot.provider_reporting_window),
                            "provenance": dict(snapshot.provenance),
                        }
                        for snapshot in history
                    ],
                }
            )
        return {
            "content_entity_id": item.id,
            "external_ref": dict(item.metadata.get("external_ref") or {}),
            "current_revision": {
                "content_revision_id": current_revision.id if current_revision else "",
                "title": current_revision.title if current_revision else item.title,
                "checksum": current_revision.checksum if current_revision else "",
                "provenance": dict(current_revision.source_provenance) if current_revision else {},
            },
            "transcript": {
                "available": current_transcript is not None,
                "artifact_id": current_transcript.artifact_id if current_transcript else "",
                "revision_id": current_transcript.revision_id if current_transcript else "",
                "language": current_transcript.language if current_transcript else "",
                "source": current_transcript.source if current_transcript else "",
                "generation_method": current_transcript.metadata.get("generation_method", "")
                if current_transcript
                else "",
                "provenance": dict(current_transcript.provenance) if current_transcript else {},
            },
            "publications": publications,
        }

    def raw_metrics_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.metrics_repository.get(snapshot_id)
        if snapshot is None:
            raise PublicationGraphError("METRICS_NOT_AVAILABLE", "Metrics snapshot was not found.")
        return {
            "snapshot_id": snapshot.snapshot_id,
            "publication_id": snapshot.publication_id,
            "raw_metrics_payload": dict(snapshot.raw_metrics_payload),
            "provider_schema_version": snapshot.provider_schema_version,
            "normalizer_id": snapshot.normalizer_id,
            "normalizer_version": snapshot.normalizer_version,
            "provenance": dict(snapshot.provenance),
        }
