from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from src.core.content.artifacts import ArtifactRepository
from src.core.content.models import ArtifactType
from src.core.content.publications import (
    InMemoryMetricsSnapshotRepository,
    PublicationGraphError,
    PublicationRepository,
    _assert_no_credentials,
)
from src.core.content.repository import ContentRepository
from src.core.runtime.events import utc_now_iso

CONTENT_PERFORMANCE_CONTEXT_SCHEMA_VERSION = "content-performance-context.v1"
_ALLOWED_REDACTION_KEYS = {
    "provider_headers_included",
    "raw_metrics_included",
    "raw_transcript_included",
    "secrets_included",
}
_BLOCKED_KEY_FRAGMENTS = ("password", "token", "secret", "credential", "api_key", "authorization")


def _assert_context_no_credentials(value: Any, *, code: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered not in _ALLOWED_REDACTION_KEYS:
                if any(fragment in lowered for fragment in _BLOCKED_KEY_FRAGMENTS) and not lowered.endswith("_ref"):
                    raise PublicationGraphError(code, "Context payload must not contain credential-shaped fields.")
            _assert_context_no_credentials(child, code=code)
    elif isinstance(value, list | tuple):
        for item in value:
            _assert_context_no_credentials(item, code=code)
    elif isinstance(value, str) and value.lower().startswith("bearer "):
        raise PublicationGraphError(code, "Context payload must not contain bearer credentials.")


@dataclass(frozen=True)
class RedactionState:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False


@dataclass(frozen=True)
class TranscriptContextState:
    available: bool
    completeness_level: str
    normalized_artifact_id: str = ""
    storage_ref: str = ""
    revision_id: str = ""
    language: str = ""
    source_type: str = ""
    generation_method: str = ""
    parser_id: str = ""
    parser_version: str = ""
    provenance_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricsSnapshotContext:
    snapshot_id: str
    publication_id: str
    observed_at: str
    provider_reporting_window: dict[str, Any]
    normalized_metrics: dict[str, dict[str, Any]]
    normalizer_id: str
    normalizer_version: str
    provider_schema_version: str
    provenance_ref: dict[str, Any]


@dataclass(frozen=True)
class PublicationContext:
    publication_id: str
    provider: str
    install_id: str
    external_ref: dict[str, Any]
    content_entity_id: str
    content_revision_id: str
    published_at: str
    observed_at: str
    state: str
    metadata: dict[str, Any]
    provenance_ref: dict[str, Any]
    metrics_history: tuple[MetricsSnapshotContext, ...]


@dataclass(frozen=True)
class ContentPerformanceContext:
    content_entity: dict[str, Any]
    current_revision: dict[str, Any]
    transcript_state: TranscriptContextState
    publications: tuple[PublicationContext, ...]
    provenance: dict[str, Any]
    redaction: RedactionState
    freshness: dict[str, Any]
    generated_at: str
    schema_version: str = CONTENT_PERFORMANCE_CONTEXT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["publications"] = list(payload["publications"])
        return payload


class ContentPerformanceContextService:
    def __init__(
        self,
        *,
        content_repository: ContentRepository,
        artifact_repository: ArtifactRepository,
        publication_repository: PublicationRepository,
        metrics_repository: InMemoryMetricsSnapshotRepository,
        clock: Callable[[], str] = utc_now_iso,
    ):
        self.content_repository = content_repository
        self.artifact_repository = artifact_repository
        self.publication_repository = publication_repository
        self.metrics_repository = metrics_repository
        self.clock = clock

    def get_context(self, content_entity_id: str) -> ContentPerformanceContext:
        item = self.content_repository.get_content_item(content_entity_id)
        if item is None:
            raise PublicationGraphError("CONTENT_ENTITY_NOT_FOUND", "Content entity was not found.")

        revisions = self.content_repository.list_revisions(content_entity_id)
        current_revision = next(
            (revision for revision in revisions if revision.id == item.current_revision_id),
            revisions[-1] if revisions else None,
        )
        transcript_state = self._transcript_state(content_entity_id, item.metadata.get("completeness", ""))
        publications = tuple(
            self._publication_context(publication)
            for publication in self.publication_repository.list_by_content(content_entity_id)
        )
        freshness = self._freshness(publications)
        context = ContentPerformanceContext(
            content_entity={
                "content_entity_id": item.id,
                "workspace_id": item.workspace_id,
                "content_type": item.content_type,
                "primary_source_type": item.primary_source_type,
                "primary_source_entity_id": item.primary_source_entity_id,
                "primary_source_ref": item.primary_source_ref,
                "external_ref": dict(item.metadata.get("external_ref") or {}),
            },
            current_revision={
                "content_revision_id": current_revision.id if current_revision else "",
                "checksum": current_revision.checksum if current_revision else "",
                "created_at": current_revision.created_at if current_revision else "",
                "change_reason": current_revision.change_reason if current_revision else "",
                "provenance_ref": dict(current_revision.source_provenance) if current_revision else {},
            },
            transcript_state=transcript_state,
            publications=publications,
            provenance={
                "content_entity_id": item.id,
                "current_revision_id": item.current_revision_id,
                "source_provenance": dict(item.source_provenance),
            },
            redaction=RedactionState(),
            freshness=freshness,
            generated_at=self.clock(),
        )
        _assert_context_no_credentials(context.to_dict(), code="content_performance_context.secret_value")
        return context

    def get_context_by_external_ref(
        self,
        *,
        provider: str,
        install_id: str,
        external_ref: dict[str, Any],
    ) -> ContentPerformanceContext:
        publication = self.publication_repository.get_by_identity(
            provider=provider,
            install_id=install_id,
            external_ref=external_ref,
        )
        if publication is None:
            canonical_ref = str(external_ref.get("canonical_ref") or "")
            item = self.content_repository.get_by_external_ref(canonical_ref) if canonical_ref else None
            if item is None:
                raise PublicationGraphError("CONTENT_ENTITY_NOT_FOUND", "Content entity was not found.")
            return self.get_context(item.id)
        return self.get_context(publication.content_entity_id)

    def get_raw_metrics_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.metrics_repository.get(snapshot_id)
        if snapshot is None:
            raise PublicationGraphError("METRICS_NOT_AVAILABLE", "Metrics snapshot was not found.")
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "publication_id": snapshot.publication_id,
            "raw_metrics_payload": dict(snapshot.raw_metrics_payload),
            "raw_metrics_ref": snapshot.raw_metrics_ref,
            "provider_schema_version": snapshot.provider_schema_version,
            "normalizer_id": snapshot.normalizer_id,
            "normalizer_version": snapshot.normalizer_version,
            "provenance_ref": dict(snapshot.provenance),
            "redaction": asdict(
                RedactionState(
                    raw_metrics_included=True,
                    raw_transcript_included=False,
                    secrets_included=False,
                    provider_headers_included=False,
                )
            ),
        }
        _assert_context_no_credentials(payload, code="raw_metrics_snapshot.secret_value")
        return payload

    def _transcript_state(self, content_entity_id: str, completeness_level: str) -> TranscriptContextState:
        transcripts = self.artifact_repository.find(
            content_entity_id=content_entity_id,
            artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value,
        )
        current = transcripts[-1] if transcripts else None
        if current is None:
            return TranscriptContextState(available=False, completeness_level=str(completeness_level or ""))
        return TranscriptContextState(
            available=True,
            completeness_level=str(completeness_level or ""),
            normalized_artifact_id=current.artifact_id,
            storage_ref=current.storage_ref,
            revision_id=current.revision_id,
            language=current.language,
            source_type=current.source,
            generation_method=str(current.metadata.get("generation_method") or ""),
            parser_id=str(current.metadata.get("parser_id") or ""),
            parser_version=str(current.metadata.get("parser_version") or ""),
            provenance_ref={
                "artifact_id": current.artifact_id,
                "content_hash": current.content_hash,
                **dict(current.provenance),
            },
        )

    def _publication_context(self, publication: Any) -> PublicationContext:
        history = self.metrics_repository.list_metrics_history(publication.publication_id)
        metric_contexts = tuple(self._metrics_context(snapshot) for snapshot in history)
        return PublicationContext(
            publication_id=publication.publication_id,
            provider=publication.provider,
            install_id=publication.install_id,
            external_ref=dict(sorted(publication.external_ref.items())),
            content_entity_id=publication.content_entity_id,
            content_revision_id=publication.content_revision_id,
            published_at=publication.published_at,
            observed_at=publication.observed_at,
            state=publication.state,
            metadata=self._safe_metadata(publication.metadata),
            provenance_ref=dict(sorted(publication.provenance.items())),
            metrics_history=metric_contexts,
        )

    def _metrics_context(self, snapshot: Any) -> MetricsSnapshotContext:
        normalized_metrics = {
            key: dict(value)
            for key, value in sorted(snapshot.normalized_metrics.items(), key=lambda item: item[0])
        }
        return MetricsSnapshotContext(
            snapshot_id=snapshot.snapshot_id,
            publication_id=snapshot.publication_id,
            observed_at=snapshot.observed_at,
            provider_reporting_window=dict(sorted(snapshot.provider_reporting_window.items())),
            normalized_metrics=normalized_metrics,
            normalizer_id=snapshot.normalizer_id,
            normalizer_version=snapshot.normalizer_version,
            provider_schema_version=snapshot.provider_schema_version,
            provenance_ref=dict(sorted(snapshot.provenance.items())),
        )

    def _freshness(self, publications: tuple[PublicationContext, ...]) -> dict[str, Any]:
        observed_values = [
            snapshot.observed_at
            for publication in publications
            for snapshot in publication.metrics_history
            if snapshot.observed_at
        ]
        return {
            "metrics_present": bool(observed_values),
            "snapshot_count": len(observed_values),
            "latest_metrics_observed_at": max(observed_values) if observed_values else "",
            "publication_count": len(publications),
        }

    def _safe_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        safe = dict(metadata)
        _assert_no_credentials(safe, code="publication_metadata.secret_value")
        return dict(sorted(safe.items()))
