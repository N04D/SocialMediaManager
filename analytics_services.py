from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import channel_store
from channel_models import PostMetricSnapshot, PublishedPost
from channel_storage import locked_json_store
from src.core.analytics import (
    ANALYTICS_FRAMEWORK_VERSION,
    ANALYTICS_INGESTION_CONTRACT_VERSION,
    ANALYTICS_READ_MODEL_CONTRACT_VERSION,
    DERIVED_METRIC_CONTRACT_VERSION,
    METRIC_DEFINITION_CONTRACT_VERSION,
    METRIC_OBSERVATION_CONTRACT_VERSION,
    PUBLICATION_ATTRIBUTION_CONTRACT_VERSION,
    AnalyticsCollectionRun,
    AnalyticsReadSnapshot,
    AttributionStatus,
    ChannelMetricObservationInput,
    DerivedMetricDefinition,
    MetricAggregationType,
    MetricDefinition,
    MetricObservation,
    MetricObservationCorrection,
    MetricObservationStatus,
    MetricValueType,
    PublicationAttribution,
)

T = TypeVar("T")

METRIC_FIELDS = ("impressions", "views", "reactions", "comments", "reposts", "shares", "clicks")
FRESHNESS_HOURS = {"fresh": 24, "aging": 72}
SAFE_SOURCE_FIELDS = {"source_run_id", "source_version", "layout_version", "metric_job_id"}


def metric_observations_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_metric_observations.json"


def metric_corrections_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_metric_corrections.json"


def publication_attributions_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_publication_attributions.json"


def collection_runs_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_collection_runs.json"


def read_snapshots_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_read_snapshots.json"


def analytics_events_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_events.json"


def analytics_audit_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_audit.json"


def analytics_integrity_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "analytics_integrity_last_scan.json"


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _load_records(path: Path, cls: type[T]) -> list[T]:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
    allowed = _fields(cls)
    records: list[T] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
        except TypeError:
            continue
    return records


def _mutate_records(path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]) -> Any:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
        allowed = _fields(cls)
        records: list[T] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
            except TypeError:
                continue
        changed, result = mutator(records)
        if changed:
            store.write([asdict(record) for record in records])
        return result


def _canonical_json(data: Any) -> str:
    import json

    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return channel_store.now_iso()


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    blocked = {
        "storage_reference",
        "storage_path",
        "local_path",
        "materialized_path",
        "screenshot_path",
        "browser_session_id",
        "takeover_url",
        "cookies",
        "html",
        "provider_secret",
        "credential",
        "visible_strings",
        "source_url",
    }
    return {
        key: value
        for key, value in dict(metadata or {}).items()
        if key not in blocked and not any(fragment in key.lower() for fragment in ("path", "cookie", "secret"))
    }


class AnalyticsValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MetricDefinitionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str, str], MetricDefinition] = {}

    def register(self, definition: MetricDefinition) -> MetricDefinition:
        key = (definition.channel_plugin_id, definition.metric_key, definition.version)
        current = self._definitions.get(key)
        if current is not None:
            if asdict(current) != asdict(definition):
                raise AnalyticsValidationError(
                    "analytics.metric_definition_conflict", "Metric definition conflicts with existing version."
                )
            return current
        self._definitions[key] = definition
        _event(
            "analytics.metric_definition.registered",
            "",
            "metric_definition",
            definition.id,
            metadata={"metric_key": definition.metric_key, "version": definition.version},
        )
        return definition

    def get(self, channel_plugin_id: str, metric_key: str, version: str = "1.0") -> MetricDefinition | None:
        return self._definitions.get((channel_plugin_id, metric_key, version))

    def latest(self, channel_plugin_id: str, metric_key: str) -> MetricDefinition | None:
        matches = [
            item
            for (plugin_id, key, _version), item in self._definitions.items()
            if plugin_id == channel_plugin_id and key == metric_key and not item.deprecated_at
        ]
        return sorted(matches, key=lambda item: item.version)[-1] if matches else None

    def list_definitions(self, channel_plugin_id: str = "") -> list[MetricDefinition]:
        values = list(self._definitions.values())
        if channel_plugin_id:
            values = [item for item in values if item.channel_plugin_id == channel_plugin_id]
        return sorted(values, key=lambda item: (item.channel_plugin_id, item.metric_key, item.version))


class DerivedMetricRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], DerivedMetricDefinition] = {}
        self.register(
            DerivedMetricDefinition(
                id="derived_engagement_rate_by_impressions_v1",
                metric_key="engagement_rate_by_impressions",
                display_name="Engagement rate by impressions",
                version="1.0",
                formula_type="percentage",
                numerator_keys=("reactions", "comments", "reposts", "shares", "clicks"),
                denominator_keys=("impressions",),
                multiplier=1.0,
                minimum_denominator=1,
                comparable_group="engagement_rate",
                aggregation_type=MetricAggregationType.WEIGHTED_AVERAGE.value,
            )
        )
        self.register(
            DerivedMetricDefinition(
                id="derived_engagement_rate_by_reach_v1",
                metric_key="engagement_rate_by_reach",
                display_name="Engagement rate by reach",
                version="1.0",
                formula_type="percentage",
                numerator_keys=("reactions", "comments", "reposts", "shares", "clicks"),
                denominator_keys=("reach",),
                multiplier=1.0,
                minimum_denominator=1,
                comparable_group="engagement_rate",
                aggregation_type=MetricAggregationType.WEIGHTED_AVERAGE.value,
            )
        )

    def register(self, definition: DerivedMetricDefinition) -> DerivedMetricDefinition:
        self._definitions[(definition.metric_key, definition.version)] = definition
        return definition

    def list_definitions(self) -> list[DerivedMetricDefinition]:
        return sorted(self._definitions.values(), key=lambda item: (item.metric_key, item.version))


class ObservationRepository:
    def create(self, observation: MetricObservation) -> tuple[MetricObservation, bool]:
        def mutate(records: list[MetricObservation]):
            existing = next((item for item in records if item.observation_key == observation.observation_key), None)
            if existing is not None:
                return False, (existing, True)
            records.append(observation)
            return True, (observation, False)

        return _mutate_records(metric_observations_path(), MetricObservation, mutate)

    def save(self, observation: MetricObservation) -> MetricObservation:
        def mutate(records: list[MetricObservation]):
            for index, record in enumerate(records):
                if record.id == observation.id:
                    records[index] = observation
                    return True, observation
            records.append(observation)
            return True, observation

        return _mutate_records(metric_observations_path(), MetricObservation, mutate)

    def get(self, observation_id: str) -> MetricObservation | None:
        return next((item for item in self.list_all() if item.id == observation_id), None)

    def list_all(self, *, workspace_id: str = "") -> list[MetricObservation]:
        records = _load_records(metric_observations_path(), MetricObservation)
        if workspace_id:
            records = [item for item in records if item.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.observed_at, item.id))

    def list_by_publication(self, publication_id: str) -> list[MetricObservation]:
        return [item for item in self.list_all() if item.publication_id == publication_id]


class CorrectionRepository:
    def create(self, correction: MetricObservationCorrection) -> MetricObservationCorrection:
        def mutate(records: list[MetricObservationCorrection]):
            records.append(correction)
            return True, correction

        return _mutate_records(metric_corrections_path(), MetricObservationCorrection, mutate)

    def list_all(self) -> list[MetricObservationCorrection]:
        return _load_records(metric_corrections_path(), MetricObservationCorrection)


class AttributionRepository:
    def create(self, attribution: PublicationAttribution) -> PublicationAttribution:
        def mutate(records: list[PublicationAttribution]):
            existing = next((item for item in records if item.publication_id == attribution.publication_id), None)
            if existing is not None:
                if existing.attribution_checksum != attribution.attribution_checksum:
                    existing.status = AttributionStatus.CONFLICTING.value
                    return True, existing
                return False, existing
            records.append(attribution)
            return True, attribution

        return _mutate_records(publication_attributions_path(), PublicationAttribution, mutate)

    def save(self, attribution: PublicationAttribution) -> PublicationAttribution:
        def mutate(records: list[PublicationAttribution]):
            for index, record in enumerate(records):
                if record.id == attribution.id:
                    records[index] = attribution
                    return True, attribution
            records.append(attribution)
            return True, attribution

        return _mutate_records(publication_attributions_path(), PublicationAttribution, mutate)

    def get_by_publication(self, publication_id: str) -> PublicationAttribution | None:
        return next((item for item in self.list_all() if item.publication_id == publication_id), None)

    def list_all(self, *, workspace_id: str = "") -> list[PublicationAttribution]:
        records = _load_records(publication_attributions_path(), PublicationAttribution)
        if workspace_id:
            records = [item for item in records if item.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.created_at, item.id))


class CollectionRunRepository:
    def create(self, run: AnalyticsCollectionRun) -> AnalyticsCollectionRun:
        def mutate(records: list[AnalyticsCollectionRun]):
            records.append(run)
            return True, run

        return _mutate_records(collection_runs_path(), AnalyticsCollectionRun, mutate)

    def save(self, run: AnalyticsCollectionRun) -> AnalyticsCollectionRun:
        def mutate(records: list[AnalyticsCollectionRun]):
            for index, record in enumerate(records):
                if record.id == run.id:
                    records[index] = run
                    return True, run
            records.append(run)
            return True, run

        return _mutate_records(collection_runs_path(), AnalyticsCollectionRun, mutate)

    def list_all(self, *, workspace_id: str = "") -> list[AnalyticsCollectionRun]:
        records = _load_records(collection_runs_path(), AnalyticsCollectionRun)
        if workspace_id:
            records = [item for item in records if item.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.started_at, item.id), reverse=True)


class ReadSnapshotRepository:
    def save(self, snapshot: AnalyticsReadSnapshot) -> AnalyticsReadSnapshot:
        def mutate(records: list[AnalyticsReadSnapshot]):
            for index, record in enumerate(records):
                if record.id == snapshot.id:
                    records[index] = snapshot
                    return True, snapshot
            records.append(snapshot)
            return True, snapshot

        return _mutate_records(read_snapshots_path(), AnalyticsReadSnapshot, mutate)

    def list_all(self) -> list[AnalyticsReadSnapshot]:
        return _load_records(read_snapshots_path(), AnalyticsReadSnapshot)


class PublicationAttributionService:
    def __init__(self, *, app_runtime, config, attribution_repository: AttributionRepository) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.attribution_repository = attribution_repository

    def resolve_publication(self, publication_id: str, *, workspace_id: str = "") -> PublicationAttribution:
        current = self.attribution_repository.get_by_publication(publication_id)
        if current is not None:
            return current
        post = channel_store.get_published_post(publication_id)
        if post is None:
            raise AnalyticsValidationError("analytics.publication_missing", "Published post was not found.")
        return self.create_attribution(post, workspace_id=workspace_id or post.channel_id)

    def create_attribution(self, post: PublishedPost, *, workspace_id: str = "") -> PublicationAttribution:
        job = channel_store.get_publish_job(post.publish_job_id)
        derivative = channel_store.get_derivative(post.derivative_id)
        evidence = dict((job.result_details_json if job else {}).get("content_publication_evidence") or {})
        metadata = dict(derivative.generation_metadata_json if derivative else {})
        snapshot = dict(metadata.get("snapshot") or {})
        target_id = str(evidence.get("publication_target_id") or metadata.get("publication_target_id") or "")
        target = None
        plan = None
        attempt = None
        if target_id:
            try:
                planning = self.app_runtime.publication_planning_service(self.config)
                target = planning.target_repository.get(target_id)
                plan = planning.plan_repository.get(target.publication_plan_id) if target is not None else None
            except Exception:
                target = None
                plan = None
            try:
                execution = self.app_runtime.publication_execution_service(self.config)
                attempts = execution.attempt_repository.list_by_target(target_id)
                attempt = attempts[-1] if attempts else None
            except Exception:
                attempt = None
        schedule_id = ""
        occurrence_id = ""
        campaign_id = ""
        if target is not None:
            target_metadata = dict(target.metadata or {})
            schedule_id = str(target_metadata.get("schedule_id") or "")
            occurrence_id = str(target_metadata.get("schedule_occurrence_id") or "")
            plan_metadata = dict(plan.metadata or {}) if plan else {}
            campaign_id = str(target_metadata.get("campaign_id") or plan_metadata.get("campaign_id") or "")
        payload = {
            "publication_id": post.id,
            "remote_publication_id": post.external_id,
            "channel_plugin_id": f"channel.{post.channel_id}"
            if not post.channel_id.startswith("channel.")
            else post.channel_id,
            "channel_account_id": post.channel_id,
            "content_item_id": evidence.get("content_item_id")
            or metadata.get("content_item_id")
            or post.source_document_id,
            "content_revision_id": evidence.get("content_revision_id") or metadata.get("content_revision_id") or "",
            "content_revision_checksum": evidence.get("revision_checksum") or metadata.get("revision_checksum") or "",
            "channel_variant_id": evidence.get("channel_variant_id") or metadata.get("channel_variant_id") or "",
            "channel_variant_checksum": evidence.get("variant_checksum") or metadata.get("variant_checksum") or "",
            "publication_plan_id": evidence.get("publication_plan_id")
            or metadata.get("publication_plan_id")
            or (plan.id if plan else ""),
            "publication_target_id": target_id,
            "schedule_id": schedule_id,
            "schedule_occurrence_id": occurrence_id,
            "campaign_id": campaign_id,
            "execution_attempt_id": attempt.id if attempt else "",
            "execution_snapshot_checksum": evidence.get("snapshot_checksum")
            or metadata.get("snapshot_checksum")
            or (attempt.snapshot_checksum if attempt else ""),
            "media_relation_ids": list(evidence.get("media_relation_ids") or metadata.get("media_relation_ids") or []),
            "media_asset_ids": list(evidence.get("source_asset_ids") or metadata.get("media_asset_ids") or []),
            "media_variant_ids": list(evidence.get("media_variant_ids") or snapshot.get("resolved_variant_ids") or []),
            "content_requirement_version": evidence.get("content_requirement_version")
            or metadata.get("content_requirement_version")
            or "",
            "media_requirement_version": evidence.get("media_requirement_version")
            or metadata.get("media_requirement_version")
            or "",
            "published_at": post.published_at,
            "remote_verified_at": (job.finished_at if job else "") or post.updated_at,
        }
        missing = [
            key
            for key in ("content_revision_id", "content_revision_checksum", "publication_target_id")
            if not payload.get(key)
        ]
        status = AttributionStatus.COMPLETE.value if not missing else AttributionStatus.PARTIAL.value
        attribution = PublicationAttribution(
            id=f"publication_attribution_{uuid4().hex}",
            workspace_id=workspace_id or post.channel_id,
            status=status,
            created_at=_now_iso(),
            attribution_checksum="",
            metadata={"missing_dimensions": missing},
            **payload,
        )
        attribution.attribution_checksum = attribution_checksum(attribution)
        saved = self.attribution_repository.create(attribution)
        _event(
            "analytics.attribution.created"
            if saved.status == AttributionStatus.COMPLETE.value
            else "analytics.attribution.partial",
            saved.workspace_id,
            "publication_attribution",
            saved.id,
        )
        return saved

    def reconcile_attribution(self, publication_id: str, *, workspace_id: str = "") -> PublicationAttribution:
        current = self.attribution_repository.get_by_publication(publication_id)
        post = channel_store.get_published_post(publication_id)
        if post is None:
            raise AnalyticsValidationError("analytics.publication_missing", "Published post was not found.")
        fresh = self.create_attribution(post, workspace_id=workspace_id or post.channel_id)
        if current is not None and current.attribution_checksum != fresh.attribution_checksum:
            fresh.status = AttributionStatus.CONFLICTING.value
            self.attribution_repository.save(fresh)
        return fresh

    def backfill(self, *, workspace_id: str = "", batch_size: int = 25, dry_run: bool = True) -> dict[str, Any]:
        batch_size = max(1, min(batch_size, 100))
        created = []
        skipped = []
        for post in channel_store.list_published_posts(channel_id=workspace_id or None)[:batch_size]:
            if self.attribution_repository.get_by_publication(post.id):
                skipped.append({"publication_id": post.id, "reason": "exists"})
                continue
            if dry_run:
                created.append({"publication_id": post.id, "status": "would_create"})
            else:
                created.append(asdict(self.create_attribution(post, workspace_id=workspace_id or post.channel_id)))
        return {"created": created, "skipped": skipped, "dry_run": dry_run}


class AnalyticsIngestionService:
    def __init__(
        self,
        *,
        app_runtime,
        config,
        metric_registry: MetricDefinitionRegistry,
        attribution_service: PublicationAttributionService,
        observation_repository: ObservationRepository,
        correction_repository: CorrectionRepository,
        collection_run_repository: CollectionRunRepository,
    ) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.metric_registry = metric_registry
        self.attribution_service = attribution_service
        self.observation_repository = observation_repository
        self.correction_repository = correction_repository
        self.collection_run_repository = collection_run_repository

    def ingest_observations(
        self,
        *,
        workspace_id: str,
        channel_plugin_id: str,
        channel_account_id: str,
        inputs: list[ChannelMetricObservationInput],
        source_type: str = "channel_runtime",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        run = AnalyticsCollectionRun(
            id=source_run_id or f"analytics_run_{uuid4().hex}",
            workspace_id=workspace_id,
            channel_plugin_id=channel_plugin_id,
            channel_account_id=channel_account_id,
            started_at=_now_iso(),
            source_version=inputs[0].source_version if inputs else "",
        )
        self.collection_run_repository.create(run)
        created: list[MetricObservation] = []
        duplicates: list[MetricObservation] = []
        failures: list[dict[str, str]] = []
        for item in inputs[:100]:
            try:
                observation, duplicate = self._ingest_one(
                    workspace_id=workspace_id,
                    channel_plugin_id=channel_plugin_id,
                    channel_account_id=channel_account_id,
                    item=item,
                    source_type=source_type,
                    source_run_id=run.id,
                )
                if duplicate:
                    duplicates.append(observation)
                    _event("analytics.observation.duplicate", workspace_id, "metric_observation", observation.id)
                else:
                    created.append(observation)
                    _event("analytics.observation.created", workspace_id, "metric_observation", observation.id)
            except AnalyticsValidationError as exc:
                failures.append({"metric_key": item.metric_key, "code": exc.code})
        run.completed_at = _now_iso()
        run.status = "completed" if not failures else "partial"
        run.publication_count = len({item.publication_id or item.remote_publication_id for item in inputs})
        run.observation_count = len(created)
        run.duplicate_count = len(duplicates)
        run.failure_count = len(failures)
        run.safe_error_codes = sorted({item["code"] for item in failures})
        run.watermark = max((item.observed_at for item in created), default="")
        self.collection_run_repository.save(run)
        _event("analytics.collection.completed", workspace_id, "analytics_collection_run", run.id)
        return {
            "run": asdict(run),
            "created": [asdict(item) for item in created],
            "duplicates": [item.id for item in duplicates],
            "failures": failures,
        }

    def ingest_metric_snapshot(
        self,
        *,
        snapshot: PostMetricSnapshot,
        published_post: PublishedPost,
        source_version: str = "linkedin.metrics.v1",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        inputs = []
        for key in METRIC_FIELDS:
            value = getattr(snapshot, key)
            if value is None:
                continue
            inputs.append(
                ChannelMetricObservationInput(
                    remote_publication_id=published_post.external_id,
                    publication_id=published_post.id,
                    metric_key=key,
                    value=value,
                    observed_at=snapshot.captured_at,
                    window_start=published_post.published_at,
                    window_end=snapshot.captured_at,
                    source_version=source_version,
                    source_evidence_reference=snapshot.id,
                    metadata={"measurement_window": "lifetime_to_date", "snapshot_id": snapshot.id},
                )
            )
        return self.ingest_observations(
            workspace_id=published_post.channel_id,
            channel_plugin_id=f"channel.{published_post.channel_id}",
            channel_account_id=published_post.channel_id,
            inputs=inputs,
            source_type="linkedin_metric_snapshot",
            source_run_id=source_run_id or f"analytics_run_{snapshot.id}",
        )

    def correct_observation(
        self,
        observation_id: str,
        *,
        corrected_value: int | float | bool | None,
        actor: str,
        reason_code: str,
        reason: str,
    ) -> MetricObservationCorrection:
        if not actor or not reason:
            raise AnalyticsValidationError(
                "analytics.correction_requires_actor_reason", "Actor and reason are required."
            )
        original = self.observation_repository.get(observation_id)
        if original is None:
            raise AnalyticsValidationError("analytics.observation_missing", "Observation was not found.")
        if original.correction_of_observation_id:
            raise AnalyticsValidationError("analytics.correction_cycle", "Corrections cannot correct corrections.")
        original.status = MetricObservationStatus.CORRECTED.value
        self.observation_repository.save(original)
        corrected = MetricObservation(
            **{
                **asdict(original),
                "id": f"metric_observation_{uuid4().hex}",
                "observed_value": corrected_value,
                "status": MetricObservationStatus.VALID.value,
                "correction_of_observation_id": original.id,
                "observation_key": observation_key(
                    workspace_id=original.workspace_id,
                    channel_plugin_id=original.channel_plugin_id,
                    channel_account_id=original.channel_account_id,
                    remote_publication_id=original.remote_publication_id,
                    metric_definition_id=original.metric_definition_id,
                    metric_definition_version=original.metric_definition_version,
                    observed_at=original.observed_at,
                    window_start=original.measurement_window_start,
                    window_end=original.measurement_window_end,
                    source_run_id=original.source_run_id,
                    observed_value=corrected_value,
                ),
            }
        )
        self.observation_repository.create(corrected)
        correction = MetricObservationCorrection(
            id=f"metric_correction_{uuid4().hex}",
            observation_id=original.id,
            corrected_observation_id=corrected.id,
            reason_code=reason_code,
            reason=reason,
            corrected_by=actor,
            corrected_at=_now_iso(),
        )
        saved = self.correction_repository.create(correction)
        _audit("analytics.observation.correct", original.workspace_id, original.publication_id, actor, reason=reason)
        _event("analytics.observation.corrected", original.workspace_id, "metric_observation", original.id)
        return saved

    def _ingest_one(
        self,
        *,
        workspace_id: str,
        channel_plugin_id: str,
        channel_account_id: str,
        item: ChannelMetricObservationInput,
        source_type: str,
        source_run_id: str,
    ) -> tuple[MetricObservation, bool]:
        definition = self.metric_registry.latest(channel_plugin_id, item.metric_key)
        if definition is None:
            raise AnalyticsValidationError("analytics.metric_definition_missing", "Metric definition is missing.")
        _validate_value(definition, item.value)
        post = channel_store.get_published_post(item.publication_id)
        if post is None:
            raise AnalyticsValidationError("analytics.publication_missing", "Published post is missing.")
        if post.channel_id != channel_account_id:
            raise AnalyticsValidationError(
                "analytics.publication_account_mismatch", "Publication belongs to another account."
            )
        self.attribution_service.resolve_publication(post.id, workspace_id=workspace_id)
        key = observation_key(
            workspace_id=workspace_id,
            channel_plugin_id=channel_plugin_id,
            channel_account_id=channel_account_id,
            remote_publication_id=item.remote_publication_id,
            metric_definition_id=definition.id,
            metric_definition_version=definition.version,
            observed_at=item.observed_at,
            window_start=item.window_start,
            window_end=item.window_end,
            source_run_id=source_run_id,
            observed_value=item.value,
        )
        observation = MetricObservation(
            id=f"metric_observation_{uuid4().hex}",
            workspace_id=workspace_id,
            channel_plugin_id=channel_plugin_id,
            channel_account_id=channel_account_id,
            publication_id=post.id,
            remote_publication_id=item.remote_publication_id,
            metric_definition_id=definition.id,
            metric_key=definition.metric_key,
            metric_definition_version=definition.version,
            observed_value=item.value,
            observed_at=item.observed_at,
            measurement_window_start=item.window_start,
            measurement_window_end=item.window_end,
            captured_at=_now_iso(),
            source_type=source_type,
            source_version=item.source_version,
            source_run_id=source_run_id,
            source_evidence_reference=item.source_evidence_reference,
            observation_key=key,
            metadata=_safe_metadata(item.metadata),
        )
        return self.observation_repository.create(observation)

    def health_check(self) -> dict[str, Any]:
        runs = self.collection_run_repository.list_all()
        return {
            "status": "ready",
            "contract_version": ANALYTICS_INGESTION_CONTRACT_VERSION,
            "definitions": len(self.metric_registry.list_definitions()),
            "last_collection_run": runs[0].started_at if runs else "",
            "last_successful_collection": next((run.completed_at for run in runs if run.status == "completed"), ""),
        }


class AnalyticsReadModelService:
    def __init__(
        self,
        *,
        app_runtime,
        config,
        metric_registry: MetricDefinitionRegistry,
        derived_metric_registry: DerivedMetricRegistry,
        observation_repository: ObservationRepository,
        attribution_repository: AttributionRepository,
        read_snapshot_repository: ReadSnapshotRepository,
    ) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.metric_registry = metric_registry
        self.derived_metric_registry = derived_metric_registry
        self.observation_repository = observation_repository
        self.attribution_repository = attribution_repository
        self.read_snapshot_repository = read_snapshot_repository

    def publication_performance(self, publication_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attribution = self.attribution_repository.get_by_publication(publication_id)
        if attribution is None:
            post = channel_store.get_published_post(publication_id)
            if post is None:
                raise AnalyticsValidationError("analytics.publication_missing", "Publication was not found.")
            attribution = self.app_runtime.analytics_attribution_service(self.config).resolve_publication(
                publication_id, workspace_id=workspace_id or post.channel_id
            )
        observations = self._active_observations(publication_id=publication_id)
        latest = latest_metrics(observations)
        deltas, delta_warnings = compute_deltas(observations, self.metric_registry)
        derived, derived_warnings = self.compute_derived(latest)
        return {
            "publication_id": publication_id,
            "remote_publication_id": attribution.remote_publication_id,
            "channel_plugin_id": attribution.channel_plugin_id,
            "channel_account_id": attribution.channel_account_id,
            "published_at": attribution.published_at,
            "content_item_id": attribution.content_item_id,
            "revision_id": attribution.content_revision_id,
            "channel_variant_id": attribution.channel_variant_id,
            "media_asset_ids": list(attribution.media_asset_ids),
            "media_variant_ids": list(attribution.media_variant_ids),
            "campaign_id": attribution.campaign_id,
            "schedule_occurrence_id": attribution.schedule_occurrence_id,
            "latest_metrics": latest,
            "metric_deltas": deltas,
            "derived_metrics": derived,
            "freshness": freshness(observations),
            "completeness": completeness(attribution, latest, self.metric_registry),
            "attribution_status": attribution.status,
            "warnings": delta_warnings + derived_warnings + list(attribution.metadata.get("missing_dimensions") or []),
        }

    def content_performance(self, content_item_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attributions = [
            item
            for item in self.attribution_repository.list_all(workspace_id=workspace_id)
            if item.content_item_id == content_item_id
        ]
        return self._aggregate_subject("content", content_item_id, attributions)

    def revision_performance(self, content_item_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attributions = [
            item
            for item in self.attribution_repository.list_all(workspace_id=workspace_id)
            if item.content_item_id == content_item_id
        ]
        return {
            "content_item_id": content_item_id,
            "comparison_validity": "valid_with_warnings"
            if len({item.channel_plugin_id for item in attributions}) > 1
            else "valid",
            "revisions": {
                revision_id: self._aggregate_subject(
                    "revision",
                    revision_id,
                    [item for item in attributions if item.content_revision_id == revision_id],
                )
                for revision_id in sorted(
                    {item.content_revision_id for item in attributions if item.content_revision_id}
                )
            },
            "warnings": ["small_sample"] if len(attributions) < 3 else [],
        }

    def variant_performance(self, content_item_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attributions = [
            item
            for item in self.attribution_repository.list_all(workspace_id=workspace_id)
            if item.content_item_id == content_item_id
        ]
        return {
            "content_item_id": content_item_id,
            "variants": {
                variant_id: self._aggregate_subject(
                    "variant",
                    variant_id,
                    [item for item in attributions if item.channel_variant_id == variant_id],
                )
                for variant_id in sorted({item.channel_variant_id for item in attributions if item.channel_variant_id})
            },
            "comparison_validity": "limited",
            "warnings": ["compare_only_compatible_metric_groups"],
        }

    def media_performance(self, asset_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attributions = [
            item
            for item in self.attribution_repository.list_all(workspace_id=workspace_id)
            if asset_id in set(item.media_asset_ids)
        ]
        payload = self._aggregate_subject("media_asset", asset_id, attributions)
        payload["attribution_note"] = "publication_included_asset"
        payload["causality_warning"] = "No causal media contribution is inferred."
        return payload

    def campaign_performance(self, campaign_id: str, *, workspace_id: str = "") -> dict[str, Any]:
        attributions = [
            item
            for item in self.attribution_repository.list_all(workspace_id=workspace_id)
            if item.campaign_id == campaign_id
        ]
        payload = self._aggregate_subject("campaign", campaign_id, attributions)
        payload["campaign_id"] = campaign_id
        payload["completed_occurrences"] = len(
            {item.schedule_occurrence_id for item in attributions if item.schedule_occurrence_id}
        )
        payload["uncertain_publications"] = 0
        return payload

    def channel_performance(
        self, *, workspace_id: str = "", channel_plugin_id: str = "", channel_account_id: str = ""
    ) -> dict[str, Any]:
        attributions = self.attribution_repository.list_all(workspace_id=workspace_id)
        if channel_plugin_id:
            attributions = [item for item in attributions if item.channel_plugin_id == channel_plugin_id]
        if channel_account_id:
            attributions = [item for item in attributions if item.channel_account_id == channel_account_id]
        return self._aggregate_subject("channel", channel_plugin_id or channel_account_id or "all", attributions)

    def compare_publications(self, publication_ids: list[str]) -> dict[str, Any]:
        performances = [self.publication_performance(publication_id) for publication_id in publication_ids[:10]]
        groups: dict[str, dict[str, Any]] = {}
        unavailable: dict[str, list[str]] = {}
        for perf in performances:
            for metric_key, metric in perf["latest_metrics"].items():
                definition = self.metric_registry.latest(perf["channel_plugin_id"], metric_key)
                comparable_group = definition.comparable_group if definition else metric_key
                groups.setdefault(comparable_group, {})[perf["publication_id"]] = {
                    "metric_key": metric_key,
                    "value": metric["value"],
                    "channel_plugin_id": perf["channel_plugin_id"],
                }
            if perf["channel_plugin_id"] == "channel.mastodon":
                unavailable[perf["publication_id"]] = ["impressions", "reach", "views", "clicks"]
        validity = "valid" if len({perf["channel_plugin_id"] for perf in performances}) <= 1 else "valid_with_warnings"
        warnings = ["observational_not_causal"] if performances else []
        if validity == "valid_with_warnings":
            warnings.extend(
                [
                    "platform_interactions_have_different_user_context",
                    "measurement_windows_may_differ",
                    "mastodon_has_no_impressions_or_reach_denominator",
                    "absolute_counts_are_observational",
                    "no_causality_claim",
                ]
            )
        return {
            "comparison_validity": validity,
            "publications": performances,
            "compatible_metric_values": groups,
            "unavailable_by_channel": unavailable,
            "warnings": warnings,
        }

    def rebuild_read_model(
        self, *, read_model_type: str, subject_id: str, workspace_id: str = ""
    ) -> AnalyticsReadSnapshot:
        if read_model_type == "publication":
            payload = self.publication_performance(subject_id, workspace_id=workspace_id)
        elif read_model_type == "content":
            payload = self.content_performance(subject_id, workspace_id=workspace_id)
        elif read_model_type == "campaign":
            payload = self.campaign_performance(subject_id, workspace_id=workspace_id)
        else:
            payload = {"subject_id": subject_id, "unsupported": True}
        snapshot = AnalyticsReadSnapshot(
            id=f"analytics_read_{read_model_type}_{subject_id}",
            workspace_id=workspace_id,
            read_model_type=read_model_type,
            subject_id=subject_id,
            filter_checksum=_checksum(
                {"read_model_type": read_model_type, "subject_id": subject_id, "workspace_id": workspace_id}
            ),
            generated_at=_now_iso(),
            source_observation_watermark=max(
                (item.captured_at for item in self.observation_repository.list_all(workspace_id=workspace_id)),
                default="",
            ),
            attribution_watermark=max(
                (item.created_at for item in self.attribution_repository.list_all(workspace_id=workspace_id)),
                default="",
            ),
            definition_versions={item.metric_key: item.version for item in self.metric_registry.list_definitions()},
            payload=payload,
            freshness=payload.get("freshness", "unknown"),
        )
        saved = self.read_snapshot_repository.save(snapshot)
        _event("analytics.read_model.rebuilt", workspace_id, "analytics_read_snapshot", saved.id)
        return saved

    def compute_derived(self, latest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        derived: dict[str, Any] = {}
        warnings: list[str] = []
        for definition in self.derived_metric_registry.list_definitions():
            numerator = sum(
                latest[key]["value"] or 0
                for key in definition.numerator_keys
                if key in latest and latest[key]["value"] is not None
            )
            denominator_values = [
                latest[key]["value"]
                for key in definition.denominator_keys
                if key in latest and latest[key]["value"] is not None
            ]
            denominator = denominator_values[0] if denominator_values else None
            if denominator is None or denominator < definition.minimum_denominator:
                reason = "denominator_unavailable" if denominator is None else "missing_or_zero_denominator"
                derived[definition.metric_key] = {
                    "value": None,
                    "version": definition.version,
                    "warning": reason,
                    "reason": reason,
                }
                warnings.append(f"{definition.metric_key}:{reason}")
                if reason == "denominator_unavailable":
                    warnings.append(f"{definition.metric_key}:missing_or_zero_denominator")
                continue
            derived[definition.metric_key] = {
                "value": (numerator / denominator) * definition.multiplier,
                "version": definition.version,
                "denominator": definition.denominator_keys[0],
                "numerator_keys": list(definition.numerator_keys),
            }
        return derived, warnings

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "contract_version": ANALYTICS_READ_MODEL_CONTRACT_VERSION,
            "observations": len(self.observation_repository.list_all()),
            "attributions": len(self.attribution_repository.list_all()),
        }

    def _active_observations(self, *, publication_id: str) -> list[MetricObservation]:
        return [
            item
            for item in self.observation_repository.list_by_publication(publication_id)
            if item.status in {MetricObservationStatus.VALID.value, MetricObservationStatus.PROVISIONAL.value}
        ]

    def _aggregate_subject(
        self, subject_type: str, subject_id: str, attributions: list[PublicationAttribution]
    ) -> dict[str, Any]:
        publication_ids = sorted({item.publication_id for item in attributions})
        latest_by_publication = [
            latest_metrics(self._active_observations(publication_id=publication_id))
            for publication_id in publication_ids
        ]
        comparable: dict[str, Any] = {}
        all_keys = sorted({key for latest in latest_by_publication for key in latest})
        for key in all_keys:
            definition = self.metric_registry.latest(attributions[0].channel_plugin_id, key) if attributions else None
            values = [
                latest[key]["value"]
                for latest in latest_by_publication
                if key in latest and latest[key]["value"] is not None
            ]
            if not values:
                continue
            if (
                definition
                and definition.aggregation_type == MetricAggregationType.LATEST.value
                and definition.cumulative
            ):
                comparable[key] = {
                    "value": sum(values),
                    "aggregation": "sum_latest_cumulative_across_unique_publications",
                    "definition_version": definition.version,
                    "comparable_group": definition.comparable_group,
                }
        return {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "publication_count": len(publication_ids),
            "channel_count": len({item.channel_plugin_id for item in attributions}),
            "account_count": len({item.channel_account_id for item in attributions}),
            "revision_count": len({item.content_revision_id for item in attributions if item.content_revision_id}),
            "latest_publication_at": max((item.published_at for item in attributions), default=""),
            "comparable_metrics": comparable,
            "per_channel_metrics": {},
            "per_revision_metrics": {},
            "per_variant_metrics": {},
            "media_breakdown": sorted({asset for item in attributions for asset in item.media_asset_ids}),
            "campaign_breakdown": sorted({item.campaign_id for item in attributions if item.campaign_id}),
            "freshness": freshness(
                [
                    obs
                    for publication_id in publication_ids
                    for obs in self._active_observations(publication_id=publication_id)
                ]
            ),
            "completeness": "complete"
            if attributions and all(item.status == AttributionStatus.COMPLETE.value for item in attributions)
            else "partial",
            "warnings": ["observational_not_causal"],
        }


class AnalyticsIntegrityService:
    def __init__(
        self,
        *,
        metric_registry: MetricDefinitionRegistry,
        observation_repository: ObservationRepository,
        attribution_repository: AttributionRepository,
        correction_repository: CorrectionRepository,
    ) -> None:
        self.metric_registry = metric_registry
        self.observation_repository = observation_repository
        self.attribution_repository = attribution_repository
        self.correction_repository = correction_repository

    def scan(self, *, workspace_id: str = "") -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        keys: dict[str, int] = {}
        for observation in self.observation_repository.list_all(workspace_id=workspace_id):
            keys[observation.observation_key] = keys.get(observation.observation_key, 0) + 1
            if (
                self.metric_registry.get(
                    observation.channel_plugin_id,
                    observation.metric_key,
                    observation.metric_definition_version,
                )
                is None
            ):
                issues.append({"code": "analytics.observation_missing_definition", "observation_id": observation.id})
            if channel_store.get_published_post(observation.publication_id) is None:
                issues.append({"code": "analytics.observation_missing_publication", "observation_id": observation.id})
        for key, count in keys.items():
            if count > 1:
                issues.append(
                    {"code": "analytics.duplicate_observation_key", "observation_key": key[:16], "count": count}
                )
        corrections = self.correction_repository.list_all()
        corrected_ids = {item.corrected_observation_id for item in corrections}
        for correction in corrections:
            if correction.observation_id in corrected_ids:
                issues.append({"code": "analytics.correction_cycle", "correction_id": correction.id})
        for attribution in self.attribution_repository.list_all(workspace_id=workspace_id):
            recalculated = attribution_checksum(attribution)
            if recalculated != attribution.attribution_checksum:
                issues.append({"code": "analytics.attribution_checksum_mismatch", "attribution_id": attribution.id})
            if channel_store.get_published_post(attribution.publication_id) is None:
                issues.append({"code": "analytics.attribution_missing_publication", "attribution_id": attribution.id})
        with _dict_store(analytics_integrity_path()) as store:
            store.write({"checked_at": _now_iso(), "issues": issues})
        return issues


def observation_key(
    *,
    workspace_id: str,
    channel_plugin_id: str,
    channel_account_id: str,
    remote_publication_id: str,
    metric_definition_id: str,
    metric_definition_version: str,
    observed_at: str,
    window_start: str,
    window_end: str,
    source_run_id: str,
    observed_value: int | float | bool | None,
) -> str:
    return _checksum(
        {
            "workspace_id": workspace_id,
            "channel_plugin_id": channel_plugin_id,
            "channel_account_id": channel_account_id,
            "remote_publication_id": remote_publication_id,
            "metric_definition_id": metric_definition_id,
            "metric_definition_version": metric_definition_version,
            "observed_at": observed_at,
            "measurement_window_start": window_start,
            "measurement_window_end": window_end,
            "source_run_id": source_run_id,
            "observed_value": observed_value,
        }
    )


def attribution_checksum(attribution: PublicationAttribution) -> str:
    return _checksum(
        {
            "publication_id": attribution.publication_id,
            "remote_publication_id": attribution.remote_publication_id,
            "revision_id": attribution.content_revision_id,
            "revision_checksum": attribution.content_revision_checksum,
            "variant_id": attribution.channel_variant_id,
            "variant_checksum": attribution.channel_variant_checksum,
            "target_snapshot_checksum": attribution.execution_snapshot_checksum,
            "media_relation_ids": sorted(attribution.media_relation_ids),
            "media_asset_ids": sorted(attribution.media_asset_ids),
            "media_variant_ids": sorted(attribution.media_variant_ids),
            "schedule_occurrence_id": attribution.schedule_occurrence_id,
            "campaign_id": attribution.campaign_id,
            "content_requirement_version": attribution.content_requirement_version,
            "media_requirement_version": attribution.media_requirement_version,
        }
    )


def latest_metrics(observations: list[MetricObservation]) -> dict[str, Any]:
    latest: dict[str, MetricObservation] = {}
    for observation in sorted(observations, key=lambda item: (item.observed_at, item.captured_at, item.id)):
        latest[observation.metric_key] = observation
    return {
        key: {
            "value": observation.observed_value,
            "observed_at": observation.observed_at,
            "definition_version": observation.metric_definition_version,
            "observation_type": observation.metadata.get("measurement_window", "lifetime_to_date"),
        }
        for key, observation in latest.items()
    }


def compute_deltas(
    observations: list[MetricObservation], registry: MetricDefinitionRegistry
) -> tuple[dict[str, Any], list[str]]:
    grouped: dict[str, list[MetricObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.metric_key, []).append(observation)
    deltas: dict[str, Any] = {}
    warnings: list[str] = []
    for key, items in grouped.items():
        items = sorted(items, key=lambda item: item.observed_at)
        if len(items) < 2:
            continue
        previous, current = items[-2], items[-1]
        definition = registry.get(current.channel_plugin_id, current.metric_key, current.metric_definition_version)
        if definition is None or not definition.cumulative:
            continue
        if previous.metric_definition_id != current.metric_definition_id:
            warnings.append(f"{key}:definition_changed")
            continue
        if current.observed_value is None or previous.observed_value is None:
            continue
        delta = float(current.observed_value) - float(previous.observed_value)
        classification = "normal_growth"
        if delta == 0:
            classification = "unchanged"
        elif delta < 0:
            classification = "regression"
            warnings.append(f"{key}:cumulative_regression")
            delta = None
        deltas[key] = {
            "value": delta,
            "classification": classification,
            "from_observed_at": previous.observed_at,
            "to_observed_at": current.observed_at,
        }
    return deltas, warnings


def freshness(observations: list[MetricObservation]) -> str:
    if not observations:
        return "unknown"
    latest_observed = max((_parse_time(item.observed_at) for item in observations), default=None)
    if latest_observed is None:
        return "unknown"
    age = datetime.now(UTC) - latest_observed
    if age <= timedelta(hours=FRESHNESS_HOURS["fresh"]):
        return "fresh"
    if age <= timedelta(hours=FRESHNESS_HOURS["aging"]):
        return "aging"
    return "stale"


def completeness(
    attribution: PublicationAttribution, latest: dict[str, Any], registry: MetricDefinitionRegistry
) -> dict[str, Any]:
    missing_dimensions = list(attribution.metadata.get("missing_dimensions") or [])
    expected = {
        item.metric_key for item in registry.list_definitions(attribution.channel_plugin_id) if not item.nullable
    }
    missing_metrics = sorted(expected - set(latest))
    if not missing_dimensions and not missing_metrics:
        status = "complete"
    elif len(missing_dimensions) <= 1:
        status = "mostly_complete"
    elif latest:
        status = "partial"
    else:
        status = "insufficient"
    return {
        "status": status,
        "attribution_status": attribution.status,
        "missing_dimensions": missing_dimensions,
        "missing_metrics": missing_metrics,
    }


def _validate_value(definition: MetricDefinition, value: int | float | bool | None) -> None:
    if value is None:
        if definition.nullable:
            return
        raise AnalyticsValidationError("analytics.metric_value_required", "Metric value is required.")
    if definition.value_type == MetricValueType.INTEGER.value and not isinstance(value, int):
        raise AnalyticsValidationError("analytics.metric_value_invalid", "Metric value must be an integer.")
    if definition.value_type == MetricValueType.DECIMAL.value and not isinstance(value, int | float):
        raise AnalyticsValidationError("analytics.metric_value_invalid", "Metric value must be numeric.")
    if definition.value_type == MetricValueType.BOOLEAN.value and not isinstance(value, bool):
        raise AnalyticsValidationError("analytics.metric_value_invalid", "Metric value must be boolean.")


def _event(
    event_type: str, workspace_id: str, target_type: str, target_id: str, metadata: dict[str, Any] | None = None
) -> None:
    with _list_store(analytics_events_path()) as store:
        records = store.read()
        records.append(
            {
                "id": f"analytics_event_{uuid4().hex}",
                "type": event_type,
                "workspace_id": workspace_id,
                "target_type": target_type,
                "target_id": target_id,
                "created_at": _now_iso(),
                "metadata": _safe_metadata(metadata),
            }
        )
        store.write(records[-500:])


def _audit(action: str, workspace_id: str, target_id: str, actor: str, *, reason: str = "", result: str = "ok") -> None:
    with _list_store(analytics_audit_path()) as store:
        records = store.read()
        records.append(
            {
                "id": f"analytics_audit_{uuid4().hex}",
                "workspace_id": workspace_id,
                "target_id": target_id,
                "actor": actor or "system",
                "action": action,
                "reason": reason,
                "result": result,
                "created_at": _now_iso(),
            }
        )
        store.write(records[-500:])


class AnalyticsServiceBundle:
    def __init__(self, *, app_runtime, config) -> None:
        self.metric_registry = MetricDefinitionRegistry()
        self.derived_metric_registry = DerivedMetricRegistry()
        self.observation_repository = ObservationRepository()
        self.correction_repository = CorrectionRepository()
        self.attribution_repository = AttributionRepository()
        self.collection_run_repository = CollectionRunRepository()
        self.read_snapshot_repository = ReadSnapshotRepository()
        self.attribution_service = PublicationAttributionService(
            app_runtime=app_runtime,
            config=config,
            attribution_repository=self.attribution_repository,
        )
        self.ingestion_service = AnalyticsIngestionService(
            app_runtime=app_runtime,
            config=config,
            metric_registry=self.metric_registry,
            attribution_service=self.attribution_service,
            observation_repository=self.observation_repository,
            correction_repository=self.correction_repository,
            collection_run_repository=self.collection_run_repository,
        )
        self.read_model_service = AnalyticsReadModelService(
            app_runtime=app_runtime,
            config=config,
            metric_registry=self.metric_registry,
            derived_metric_registry=self.derived_metric_registry,
            observation_repository=self.observation_repository,
            attribution_repository=self.attribution_repository,
            read_snapshot_repository=self.read_snapshot_repository,
        )
        self.integrity_service = AnalyticsIntegrityService(
            metric_registry=self.metric_registry,
            observation_repository=self.observation_repository,
            attribution_repository=self.attribution_repository,
            correction_repository=self.correction_repository,
        )

    def health_check(self) -> dict[str, Any]:
        runs = self.collection_run_repository.list_all()
        partial = sum(
            item.status in {AttributionStatus.PARTIAL.value, AttributionStatus.UNRESOLVED.value}
            for item in self.attribution_repository.list_all()
        )
        return {
            "status": "ready",
            "analytics_framework_version": ANALYTICS_FRAMEWORK_VERSION,
            "repositories": {
                "observations": True,
                "corrections": True,
                "attributions": True,
                "collection_runs": True,
                "read_snapshots": True,
            },
            "metric_registry": True,
            "definitions": len(self.metric_registry.list_definitions()),
            "attribution_service": True,
            "ingestion_service": self.ingestion_service.health_check(),
            "read_model_service": self.read_model_service.health_check(),
            "last_collection_run": runs[0].started_at if runs else "",
            "partial_attribution_count": partial,
            "contract_versions": {
                "metric_definition": METRIC_DEFINITION_CONTRACT_VERSION,
                "observation": METRIC_OBSERVATION_CONTRACT_VERSION,
                "attribution": PUBLICATION_ATTRIBUTION_CONTRACT_VERSION,
                "derived_metric": DERIVED_METRIC_CONTRACT_VERSION,
                "read_model": ANALYTICS_READ_MODEL_CONTRACT_VERSION,
                "ingestion": ANALYTICS_INGESTION_CONTRACT_VERSION,
            },
        }
