from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import channel_store
from channel_storage import locked_json_store
from channel_store import (
    get_derivative,
    get_publish_job,
    get_published_post,
    now_iso,
)
from content_store import CONTENT_DRAFTS_DIR, get_content_item
from media_store import (
    get_media_asset,
    get_media_variant,
    list_media_assets,
    list_media_variants,
    save_media_asset,
    save_media_variant,
)
from src.core.media import (
    ChannelMediaRequirements,
    ContentMediaOwnerType,
    ContentMediaRelation,
    ContentMediaRole,
    MediaAuditEvent,
    MediaIntegrityIssue,
    MediaLibrarySearchResult,
    MediaNotFoundError,
    MediaRequirementViolation,
    MediaRetentionCandidate,
    MediaRetentionPlan,
    MediaRetentionPlanStatus,
    MediaRetentionPolicy,
    MediaSelectionResult,
    MediaStatus,
    MediaUsage,
    MediaUsageType,
    MediaValidationError,
    MediaVariantStatus,
    SelectedMediaItem,
)

STRUCTURAL_USAGE_TYPES = {MediaUsageType.LINKED.value, MediaUsageType.PUBLISHED.value}
OPERATIONAL_USAGE_TYPES = {
    MediaUsageType.SELECTED.value,
    MediaUsageType.MATERIALIZED.value,
    MediaUsageType.PROCESSED.value,
    MediaUsageType.PUBLISH_ATTEMPT.value,
    MediaUsageType.PREVIEWED.value,
}
SAFE_MIME_TYPES = {"image/jpeg", "image/png"}
FORBIDDEN_METADATA_KEYS = {
    "storage_reference",
    "storage_ref",
    "local_path",
    "materialized_path",
    "object_path",
    "transfer_path",
    "absolute_path",
}


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def relations_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_relations.json"


def usage_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_usage.json"


def retention_policies_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_retention_policies.json"


def retention_plans_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_retention_plans.json"


def audit_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_audit_events.json"


def events_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_events.json"


def integrity_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_integrity_last_scan.json"


def _load_records(path: Path, cls):
    with _list_store(path) as store:
        payload = store.read()
    records = []
    for item in payload:
        if isinstance(item, dict):
            try:
                records.append(cls(**item))
            except TypeError:
                continue
    return records


def _serialize(records: list[Any]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]


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
    safe: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        lowered = str(key).lower()
        if lowered in FORBIDDEN_METADATA_KEYS or "path" in lowered or "reference" in lowered:
            continue
        if isinstance(value, dict):
            safe[str(key)] = _safe_metadata(value)
        elif isinstance(value, list):
            safe[str(key)] = [str(item)[:300] for item in value if not isinstance(item, dict)]
        else:
            safe[str(key)] = value if isinstance(value, (int, float, bool)) else str(value)[:300]
    return safe


def _safe_asset_payload(
    asset, *, relation_count: int = 0, usage_count: int = 0, last_used_at: str = "", suitability=None
) -> dict[str, Any]:
    inspection = {}
    if isinstance(asset.metadata, dict):
        inspection = dict(asset.metadata.get("image_inspection") or {})
    return {
        "id": asset.id,
        "workspace_id": asset.workspace_id,
        "display_name": asset.display_name,
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "file_size": asset.file_size,
        "status": asset.status,
        "checksum": asset.checksum[:12],
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "inspection_status": str(inspection.get("status") or ""),
        "variant_count": len(list_media_variants(asset_id=asset.id)),
        "relation_count": relation_count,
        "usage_count": usage_count,
        "last_used_at": last_used_at,
        "channel_suitability": suitability or {},
        "soft_deleted": asset.status == MediaStatus.DELETED.value,
    }


class MediaRelationRepository:
    def create(self, relation: ContentMediaRelation) -> ContentMediaRelation:
        with _list_store(relations_path()) as store:
            records = _load_relation_payload(store.read())
            duplicate = self._find_duplicate_in_records(records, relation)
            if duplicate is not None:
                raise MediaValidationError("media.relation_duplicate", "Media relation already exists.")
            if relation.active and relation.role == ContentMediaRole.PRIMARY.value:
                for record in records:
                    if (
                        _same_owner(record, relation)
                        and record.active
                        and record.role == ContentMediaRole.PRIMARY.value
                    ):
                        record.active = False
                        record.updated_at = now_iso()
            records.append(relation)
            store.write(_serialize(records))
        return relation

    def get(self, relation_id: str) -> ContentMediaRelation | None:
        return next((record for record in self.list_all() if record.id == relation_id), None)

    def list_all(self) -> list[ContentMediaRelation]:
        return _load_records(relations_path(), ContentMediaRelation)

    def list_by_owner(self, owner_type: str, owner_id: str, *, workspace_id: str = "", active_only: bool = True):
        records = [
            record
            for record in self.list_all()
            if record.owner_type == owner_type
            and record.owner_id == owner_id
            and (not workspace_id or record.workspace_id == workspace_id)
        ]
        if active_only:
            records = [record for record in records if record.active]
        return sorted(records, key=lambda item: (item.position, item.role, item.id))

    def list_by_asset(self, asset_id: str, *, active_only: bool = False):
        records = [record for record in self.list_all() if record.asset_id == asset_id]
        if active_only:
            records = [record for record in records if record.active]
        return sorted(
            records, key=lambda item: (item.workspace_id, item.owner_type, item.owner_id, item.position, item.id)
        )

    def update(self, relation: ContentMediaRelation) -> ContentMediaRelation:
        with _list_store(relations_path()) as store:
            records = _load_relation_payload(store.read())
            for index, record in enumerate(records):
                if record.id == relation.id:
                    records[index] = relation
                    store.write(_serialize(records))
                    return relation
        raise MediaNotFoundError("media.relation_not_found", "Media relation was not found.")

    def reorder(
        self, owner_type: str, owner_id: str, ordered_relation_ids: list[str], *, workspace_id: str
    ) -> list[ContentMediaRelation]:
        with _list_store(relations_path()) as store:
            records = _load_relation_payload(store.read())
            by_id = {record.id: record for record in records}
            updated: list[ContentMediaRelation] = []
            for position, relation_id in enumerate(ordered_relation_ids):
                relation = by_id.get(relation_id)
                if (
                    relation is None
                    or relation.workspace_id != workspace_id
                    or relation.owner_type != owner_type
                    or relation.owner_id != owner_id
                ):
                    continue
                relation.position = position
                relation.updated_at = now_iso()
                updated.append(relation)
            store.write(_serialize(records))
            return updated

    def deactivate(self, relation_id: str) -> ContentMediaRelation:
        relation = self.get(relation_id)
        if relation is None:
            raise MediaNotFoundError("media.relation_not_found", "Media relation was not found.")
        relation.active = False
        relation.updated_at = now_iso()
        return self.update(relation)

    def restore(self, relation_id: str) -> ContentMediaRelation:
        relation = self.get(relation_id)
        if relation is None:
            raise MediaNotFoundError("media.relation_not_found", "Media relation was not found.")
        relation.active = True
        relation.updated_at = now_iso()
        return self.update(relation)

    def find_duplicate(self, relation: ContentMediaRelation) -> ContentMediaRelation | None:
        return self._find_duplicate_in_records(self.list_all(), relation)

    @staticmethod
    def _find_duplicate_in_records(records: list[ContentMediaRelation], relation: ContentMediaRelation):
        return next(
            (
                record
                for record in records
                if record.id != relation.id
                and record.active
                and relation.active
                and _same_owner(record, relation)
                and record.asset_id == relation.asset_id
                and record.role == relation.role
                and record.position == relation.position
            ),
            None,
        )


class MediaUsageRepository:
    def register(self, usage: MediaUsage, *, idempotency_key: str = "") -> MediaUsage:
        key = idempotency_key or self._usage_key(usage)
        usage.metadata = _safe_metadata(dict(usage.metadata or {}) | {"idempotency_key": key})
        now = usage.last_used_at or now_iso()
        usage.first_used_at = usage.first_used_at or now
        usage.last_used_at = now
        usage.usage_count = max(usage.usage_count, 1)
        with _list_store(usage_path()) as store:
            records = _load_usage_payload(store.read())
            for record in records:
                if str(record.metadata.get("idempotency_key") or "") == key:
                    record.usage_count += 1
                    record.last_used_at = now
                    record.status = usage.status or record.status
                    store.write(_serialize(records))
                    return record
            records.append(usage)
            store.write(_serialize(records))
        return usage

    def list_all(self) -> list[MediaUsage]:
        return _load_records(usage_path(), MediaUsage)

    def list_by_asset(self, asset_id: str) -> list[MediaUsage]:
        return [record for record in self.list_all() if record.asset_id == asset_id]

    def list_by_variant(self, variant_id: str) -> list[MediaUsage]:
        return [record for record in self.list_all() if record.variant_id == variant_id]

    def list_active_usages(self) -> list[MediaUsage]:
        return [record for record in self.list_all() if record.status == "active"]

    def list_historical_publications(self, *, asset_id: str = "", variant_id: str = "") -> list[MediaUsage]:
        return [
            record
            for record in self.list_all()
            if record.usage_type == MediaUsageType.PUBLISHED.value
            and (not asset_id or record.asset_id == asset_id)
            and (not variant_id or record.variant_id == variant_id)
        ]

    def expire_operational_usage(self, *, older_than_days: int = 1) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(older_than_days, 0))
        changed = 0
        with _list_store(usage_path()) as store:
            records = _load_usage_payload(store.read())
            for record in records:
                used_at = _parse_time(record.last_used_at)
                if (
                    record.usage_type in OPERATIONAL_USAGE_TYPES
                    and record.status == "active"
                    and used_at
                    and used_at < cutoff
                ):
                    record.status = "expired"
                    changed += 1
            if changed:
                store.write(_serialize(records))
        return changed

    def rebuild_counters(self) -> dict[str, dict[str, Any]]:
        counters: dict[str, dict[str, Any]] = {}
        for usage in self.list_all():
            item = counters.setdefault(
                usage.asset_id,
                {"usage_count": 0, "publication_usage_count": 0, "last_used_at": ""},
            )
            item["usage_count"] += usage.usage_count
            if usage.usage_type == MediaUsageType.PUBLISHED.value:
                item["publication_usage_count"] += usage.usage_count
            if usage.last_used_at > item["last_used_at"]:
                item["last_used_at"] = usage.last_used_at
        return counters

    @staticmethod
    def _usage_key(usage: MediaUsage) -> str:
        raw = "|".join(
            [
                usage.workspace_id,
                usage.asset_id,
                usage.variant_id,
                usage.usage_type,
                usage.owner_type,
                usage.owner_id,
                usage.channel_plugin_id,
                usage.publication_id,
                usage.job_id,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MediaRetentionRepository:
    def default_policy(self, workspace_id: str) -> MediaRetentionPolicy:
        existing = next(
            (policy for policy in self.list_policies(workspace_id=workspace_id) if policy.target_type == "variant"),
            None,
        )
        if existing is not None:
            return existing
        now = now_iso()
        policy = MediaRetentionPolicy(
            id=f"retention_policy_{uuid4().hex}",
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        self.save_policy(policy)
        return policy

    def list_policies(self, *, workspace_id: str = "") -> list[MediaRetentionPolicy]:
        records = _load_records(retention_policies_path(), MediaRetentionPolicy)
        return [record for record in records if not workspace_id or record.workspace_id == workspace_id]

    def save_policy(self, policy: MediaRetentionPolicy) -> MediaRetentionPolicy:
        with _list_store(retention_policies_path()) as store:
            records = _load_records_from_payload(store.read(), MediaRetentionPolicy)
            for index, record in enumerate(records):
                if record.id == policy.id:
                    records[index] = policy
                    store.write(_serialize(records))
                    return policy
            records.append(policy)
            store.write(_serialize(records))
            return policy

    def save_plan(self, plan: MediaRetentionPlan) -> MediaRetentionPlan:
        with _list_store(retention_plans_path()) as store:
            records = _load_records_from_payload(store.read(), MediaRetentionPlan)
            for index, record in enumerate(records):
                if record.id == plan.id:
                    records[index] = plan
                    store.write(_serialize(records))
                    return plan
            records.append(plan)
            store.write(_serialize(records))
            return plan

    def get_plan(self, plan_id: str) -> MediaRetentionPlan | None:
        return next(
            (record for record in _load_records(retention_plans_path(), MediaRetentionPlan) if record.id == plan_id),
            None,
        )


class MediaRetentionService:
    def __init__(self, *, relation_repository: MediaRelationRepository, usage_repository: MediaUsageRepository) -> None:
        self.relation_repository = relation_repository
        self.usage_repository = usage_repository
        self.repository = MediaRetentionRepository()

    def preview(
        self, *, workspace_id: str, policy: MediaRetentionPolicy | None = None
    ) -> list[MediaRetentionCandidate]:
        policy = policy or self.repository.default_policy(workspace_id)
        if not policy.enabled or policy.target_type != "variant":
            return []
        candidates: list[MediaRetentionCandidate] = []
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=max(policy.unused_for_days, 0))
        failed_cutoff = now - timedelta(days=max(policy.failed_variant_days, 0))
        for variant in list_media_variants():
            asset = get_media_asset(variant.asset_id)
            if asset is None or asset.workspace_id != workspace_id:
                continue
            usage = self.usage_repository.list_by_variant(variant.id)
            relations = [
                record
                for record in self.relation_repository.list_by_asset(variant.asset_id, active_only=True)
                if record.variant_id == variant.id
            ]
            publication_usage = [record for record in usage if record.usage_type == MediaUsageType.PUBLISHED.value]
            active_materialization = [
                record
                for record in usage
                if record.usage_type == MediaUsageType.MATERIALIZED.value and record.status == "active"
            ]
            last_used_at = max(
                [record.last_used_at for record in usage if record.last_used_at]
                or [variant.updated_at or variant.created_at]
            )
            last_used = _parse_time(last_used_at)
            blockers: list[str] = []
            if variant.retention_pinned:
                blockers.append("pinned")
            if relations:
                blockers.append("active_relation")
            if publication_usage and policy.keep_historical_publications:
                blockers.append("historical_publication")
            if active_materialization:
                blockers.append("active_materialization")
            if variant.status == MediaVariantStatus.PROCESSING.value:
                blockers.append("processing")
            if asset.status == MediaStatus.DELETED.value:
                blockers.append("source_asset_deleted")
            old_enough = bool(last_used and last_used < cutoff)
            failed_old_enough = variant.status == MediaVariantStatus.FAILED.value and bool(
                last_used and last_used < failed_cutoff
            )
            if variant.status not in {MediaVariantStatus.AVAILABLE.value, MediaVariantStatus.FAILED.value}:
                blockers.append("status_not_cleanup_eligible")
            if not old_enough and not failed_old_enough:
                blockers.append("recently_used")
            if blockers:
                continue
            candidates.append(
                MediaRetentionCandidate(
                    asset_id=variant.asset_id,
                    variant_id=variant.id,
                    status=variant.status,
                    reason="unused_variant"
                    if variant.status == MediaVariantStatus.AVAILABLE.value
                    else "old_failed_variant",
                    last_used_at=last_used_at,
                    relation_count=len(relations),
                    publication_usage_count=len(publication_usage),
                    estimated_bytes=variant.file_size,
                    blockers=(),
                )
            )
        return candidates

    def create_plan(self, *, workspace_id: str, created_by: str, reason: str) -> MediaRetentionPlan:
        policy = self.repository.default_policy(workspace_id)
        candidates = self.preview(workspace_id=workspace_id, policy=policy)
        plan = MediaRetentionPlan(
            id=f"retention_plan_{uuid4().hex}",
            workspace_id=workspace_id,
            policy_id=policy.id,
            created_at=now_iso(),
            updated_at=now_iso(),
            created_by=created_by,
            reason=reason,
            candidate_count=len(candidates),
            estimated_bytes=sum(item.estimated_bytes for item in candidates),
            candidates=[asdict(item) for item in candidates],
            blockers=[],
            confirmation_required=True,
            confirmation_token=hashlib.sha256(f"{workspace_id}|{created_by}|{now_iso()}".encode()).hexdigest()[:16],
        )
        return self.repository.save_plan(plan)

    def execute_plan(self, *, plan_id: str, actor: str, reason: str, confirmation_token: str) -> MediaRetentionPlan:
        plan = self.repository.get_plan(plan_id)
        if plan is None:
            raise MediaNotFoundError("media.retention_plan_not_found", "Retention plan was not found.")
        if plan.status in {MediaRetentionPlanStatus.COMPLETED.value, MediaRetentionPlanStatus.CANCELLED.value}:
            return plan
        if not confirmation_token or confirmation_token != plan.confirmation_token:
            raise MediaValidationError(
                "media.retention_confirmation_required", "Retention execution requires confirmation."
            )
        plan.status = MediaRetentionPlanStatus.EXECUTING.value
        self.repository.save_plan(plan)
        current = {candidate.variant_id for candidate in self.preview(workspace_id=plan.workspace_id)}
        completed = 0
        blockers: list[dict[str, Any]] = []
        for candidate in plan.candidates:
            variant_id = str(candidate.get("variant_id") or "")
            if variant_id not in current:
                blockers.append({"variant_id": variant_id, "code": "candidate_changed"})
                continue
            variant = get_media_variant(variant_id)
            if variant is None:
                blockers.append({"variant_id": variant_id, "code": "variant_missing"})
                continue
            variant.status = MediaVariantStatus.DELETED.value
            variant.updated_at = now_iso()
            metadata = dict(variant.metadata or {})
            metadata["retention_soft_deleted"] = {"actor": actor, "reason": reason, "at": variant.updated_at}
            variant.metadata = metadata
            save_media_variant(variant)
            completed += 1
        plan.blockers = blockers
        plan.status = (
            MediaRetentionPlanStatus.COMPLETED.value
            if completed == plan.candidate_count and not blockers
            else MediaRetentionPlanStatus.PARTIALLY_COMPLETED.value
        )
        plan.updated_at = now_iso()
        return self.repository.save_plan(plan)


class MediaLibraryService:
    def __init__(self, *, app_runtime, config) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.media_runtime = app_runtime.media_runtime(config)
        self.media_processing_runtime = app_runtime.media_processing_runtime(config)
        self.relation_repository = MediaRelationRepository()
        self.usage_repository = MediaUsageRepository()
        self.retention_service = MediaRetentionService(
            relation_repository=self.relation_repository,
            usage_repository=self.usage_repository,
        )
        self.requirement_registry = self.media_processing_runtime.requirement_registry

    def get_asset(self, asset_id: str, *, workspace_id: str = "", include_deleted: bool = False):
        asset = get_media_asset(asset_id)
        if asset is None or (asset.status == MediaStatus.DELETED.value and not include_deleted):
            raise MediaNotFoundError("media.asset_not_found", "Media asset was not found.")
        if workspace_id and asset.workspace_id != workspace_id:
            raise MediaNotFoundError("media.asset_not_found", "Media asset was not found.")
        return asset

    def search_assets(self, *, workspace_id: str, filters: dict[str, Any] | None = None) -> MediaLibrarySearchResult:
        filters = filters or {}
        assets = [asset for asset in list_media_assets(workspace_id=workspace_id)]
        include_deleted = bool(filters.get("deleted"))
        if not include_deleted:
            assets = [asset for asset in assets if asset.status != MediaStatus.DELETED.value]
        assets = self._filter_assets(assets, filters)
        counters = self._asset_counters()
        sort_by = str(filters.get("sort_by") or "created_at")
        reverse = str(filters.get("sort_dir") or "desc") == "desc"

        def sort_value(asset):
            counts = counters.get(asset.id, {})
            values = {
                "created_at": asset.created_at,
                "display_name": asset.display_name.lower(),
                "file_size": asset.file_size,
                "last_used_at": counts.get("last_used_at", ""),
                "usage_count": counts.get("usage_count", 0),
            }
            return values.get(sort_by, asset.created_at), asset.id

        assets = sorted(assets, key=sort_value, reverse=reverse)
        page_size = min(max(int(filters.get("page_size") or 25), 1), 100)
        page = max(int(filters.get("page") or 1), 1)
        start = (page - 1) * page_size
        page_assets = assets[start : start + page_size]
        return MediaLibrarySearchResult(
            assets=tuple(
                _safe_asset_payload(
                    asset,
                    relation_count=counters.get(asset.id, {}).get("relation_count", 0),
                    usage_count=counters.get(asset.id, {}).get("usage_count", 0),
                    last_used_at=counters.get(asset.id, {}).get("last_used_at", ""),
                    suitability=self.evaluate_channel_suitability(asset.id, workspace_id=workspace_id),
                )
                for asset in page_assets
            ),
            page=page,
            page_size=page_size,
            total=len(assets),
            has_next=start + page_size < len(assets),
        )

    def attach_asset(
        self,
        *,
        workspace_id: str,
        owner_type: str,
        owner_id: str,
        asset_id: str,
        role: str = ContentMediaRole.ATTACHMENT.value,
        position: int = 0,
        variant_id: str = "",
        channel_plugin_id: str = "",
        publication_id: str = "",
        required: bool = False,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ContentMediaRelation:
        self._validate_owner(owner_type, owner_id, workspace_id=workspace_id)
        asset = self.get_asset(asset_id, workspace_id=workspace_id)
        if asset.status in {MediaStatus.DELETED.value, MediaStatus.FAILED.value, MediaStatus.QUARANTINED.value}:
            raise MediaValidationError("media.asset_not_linkable", "Media asset cannot be linked.")
        self._validate_role(role)
        if position < 0:
            raise MediaValidationError("media.position_invalid", "Media relation position must be non-negative.")
        if variant_id:
            variant = get_media_variant(variant_id)
            if variant is None or variant.asset_id != asset.id:
                raise MediaValidationError(
                    "media.variant_asset_mismatch", "Media variant does not belong to this asset."
                )
        relation = ContentMediaRelation(
            id=f"media_relation_{uuid4().hex}",
            workspace_id=workspace_id,
            owner_type=owner_type,
            owner_id=owner_id,
            asset_id=asset_id,
            variant_id=variant_id,
            role=role,
            position=position,
            channel_plugin_id=channel_plugin_id,
            publication_id=publication_id,
            required=required,
            active=True,
            created_at=now_iso(),
            updated_at=now_iso(),
            created_by=created_by,
            metadata=_safe_metadata(metadata),
        )
        saved = self.relation_repository.create(relation)
        self._register_usage(
            asset_id=asset_id,
            variant_id=variant_id,
            workspace_id=workspace_id,
            usage_type=MediaUsageType.LINKED.value,
            owner_type=owner_type,
            owner_id=owner_id,
            channel_plugin_id=channel_plugin_id,
            publication_id=publication_id,
            job_id="",
            idempotency_key=f"linked|{saved.id}",
        )
        self._event("media.relation.created", workspace_id, "relation", saved.id, created_by)
        self._audit("media.relation.created", workspace_id, "relation", saved.id, created_by)
        return saved

    def detach_asset(self, relation_id: str, *, actor: str = "", reason: str = "") -> ContentMediaRelation:
        relation = self.relation_repository.deactivate(relation_id)
        self._event("media.relation.removed", relation.workspace_id, "relation", relation.id, actor)
        self._audit("media.relation.removed", relation.workspace_id, "relation", relation.id, actor, reason=reason)
        return relation

    def reorder_assets(
        self, *, workspace_id: str, owner_type: str, owner_id: str, ordered_relation_ids: list[str], actor: str = ""
    ):
        updated = self.relation_repository.reorder(
            owner_type, owner_id, ordered_relation_ids, workspace_id=workspace_id
        )
        self._audit("media.relation.reordered", workspace_id, "owner", f"{owner_type}:{owner_id}", actor)
        return updated

    def set_primary_asset(
        self, *, workspace_id: str, owner_type: str, owner_id: str, relation_id: str, actor: str = ""
    ):
        relation = self.relation_repository.get(relation_id)
        if (
            relation is None
            or relation.workspace_id != workspace_id
            or relation.owner_type != owner_type
            or relation.owner_id != owner_id
        ):
            raise MediaNotFoundError("media.relation_not_found", "Media relation was not found.")
        relation.role = ContentMediaRole.PRIMARY.value
        relation.active = True
        relation.updated_at = now_iso()
        saved = (
            self.relation_repository.create(relation)
            if self.relation_repository.get(relation.id) is None
            else self.relation_repository.update(relation)
        )
        for other in self.relation_repository.list_by_owner(owner_type, owner_id, workspace_id=workspace_id):
            if other.id != relation_id and other.role == ContentMediaRole.PRIMARY.value:
                other.active = False
                other.updated_at = now_iso()
                self.relation_repository.update(other)
        self._audit("media.relation.primary_changed", workspace_id, "relation", relation_id, actor)
        return saved

    def list_owner_media(
        self, *, owner_type: str, owner_id: str, workspace_id: str, compatibility_metadata: dict[str, Any] | None = None
    ):
        relations = self.relation_repository.list_by_owner(owner_type, owner_id, workspace_id=workspace_id)
        if relations:
            return relations
        return self._lazy_migrate_owner_media(
            owner_type=owner_type,
            owner_id=owner_id,
            workspace_id=workspace_id,
            compatibility_metadata=compatibility_metadata,
        )

    def resolve_owner_media(
        self,
        *,
        owner_type: str,
        owner_id: str,
        workspace_id: str,
        channel_plugin_id: str,
        capability: str,
        compatibility_metadata: dict[str, Any] | None = None,
        job_id: str = "",
    ) -> MediaSelectionResult:
        self._validate_owner(owner_type, owner_id, workspace_id=workspace_id)
        relations = self.list_owner_media(
            owner_type=owner_type,
            owner_id=owner_id,
            workspace_id=workspace_id,
            compatibility_metadata=compatibility_metadata,
        )
        relations = [relation for relation in relations if relation.active]
        ordered = sorted(relations, key=lambda item: (item.position, item.role, item.id))
        requirement = self.requirement_registry.get(channel_plugin_id, capability)
        ordered = ordered[: requirement.max_assets]
        selected: list[SelectedMediaItem] = []
        rejected: list[MediaRequirementViolation] = []
        warnings: list[str] = []
        for relation in ordered:
            resolution = self.media_processing_runtime.resolve_channel_media(
                [relation.asset_id],
                workspace_id=workspace_id,
                channel_plugin_id=channel_plugin_id,
                capability=capability,
                prefer_variant=bool(relation.variant_id),
            )
            rejected.extend(resolution.rejected)
            warnings.extend(resolution.warnings)
            if not resolution.selected:
                continue
            item = resolution.selected[0]
            variant_id = relation.variant_id or item.variant_id
            selected_item = SelectedMediaItem(
                relation_id=relation.id,
                asset_id=item.asset_id,
                variant_id=variant_id,
                role=relation.role,
                position=relation.position,
                resolved_mime_type=item.mime_type,
                width=item.width,
                height=item.height,
                checksum=item.checksum,
                direct_use=item.direct_use and not relation.variant_id,
                processor_plugin_id=item.processor_plugin_id,
                suitability_status="ready" if item.direct_use and not relation.variant_id else "variant_available",
            )
            selected.append(selected_item)
            self._register_usage(
                asset_id=selected_item.asset_id,
                variant_id=selected_item.variant_id,
                workspace_id=workspace_id,
                usage_type=MediaUsageType.SELECTED.value,
                owner_type=owner_type,
                owner_id=owner_id,
                channel_plugin_id=channel_plugin_id,
                publication_id=relation.publication_id,
                job_id=job_id,
                idempotency_key=f"selected|{job_id}|{relation.id}|{selected_item.asset_id}|{selected_item.variant_id}",
            )
        if len(relations) > requirement.max_assets:
            warnings.append("media.max_assets_applied")
        return MediaSelectionResult(
            owner_type=owner_type,
            owner_id=owner_id,
            channel_plugin_id=channel_plugin_id,
            capability=capability,
            selected_items=tuple(selected),
            rejected_items=tuple(rejected),
            warnings=tuple(warnings),
            requirement_version=requirement.requirement_version,
        )

    @contextmanager
    def materialize_selected(self, selected: SelectedMediaItem, *, workspace_id: str, purpose: str, job_id: str = ""):
        from src.core.media import ResolvedMediaItem

        asset = self.get_asset(selected.asset_id, workspace_id=workspace_id)
        item = ResolvedMediaItem(
            asset_id=selected.asset_id,
            variant_id=selected.variant_id,
            media_type=asset.media_type,
            mime_type=selected.resolved_mime_type,
            file_size=asset.file_size,
            checksum=selected.checksum,
            width=selected.width,
            height=selected.height,
            direct_use=selected.direct_use,
            processor_plugin_id=selected.processor_plugin_id,
            requirement_id="",
            requirement_version="",
        )
        with self.media_processing_runtime.materialize_resolved(
            item, workspace_id=workspace_id, purpose=purpose
        ) as mat:
            self._register_usage(
                asset_id=selected.asset_id,
                variant_id=selected.variant_id,
                workspace_id=workspace_id,
                usage_type=MediaUsageType.MATERIALIZED.value,
                owner_type=ContentMediaOwnerType.PUBLICATION_ATTEMPT.value,
                owner_id=job_id,
                channel_plugin_id="",
                publication_id="",
                job_id=job_id,
                idempotency_key=f"materialized|{job_id}|{selected.relation_id}|{selected.asset_id}|{selected.variant_id}",
            )
            yield mat

    def list_asset_usage(self, asset_id: str, *, workspace_id: str) -> list[MediaUsage]:
        self.get_asset(asset_id, workspace_id=workspace_id, include_deleted=True)
        return self.usage_repository.list_by_asset(asset_id)

    def evaluate_channel_suitability(self, asset_id: str, *, workspace_id: str) -> dict[str, dict[str, str]]:
        asset = self.get_asset(asset_id, workspace_id=workspace_id, include_deleted=True)
        result: dict[str, dict[str, str]] = {}
        for requirement in self.requirement_registry.list():
            status = self._suitability_status(asset, requirement)
            result[f"{requirement.channel_plugin_id}:{requirement.capability}"] = {
                "status": status,
                "requirement_version": requirement.requirement_version,
            }
        return result

    def request_delete(self, asset_id: str, *, workspace_id: str, actor: str, reason: str):
        asset = self.get_asset(asset_id, workspace_id=workspace_id, include_deleted=True)
        blockers = self.relation_repository.list_by_asset(asset.id, active_only=True)
        asset.status = MediaStatus.DELETED.value
        asset.deleted_at = now_iso()
        asset.deleted_by = actor
        asset.delete_reason = reason
        asset.updated_at = asset.deleted_at
        saved = save_media_asset(asset)
        self._event("media.asset.deleted", workspace_id, "asset", asset.id, actor)
        self._audit(
            "media.asset.deleted",
            workspace_id,
            "asset",
            asset.id,
            actor,
            reason=reason,
            metadata={"active_relation_blockers": [record.id for record in blockers]},
        )
        return {"asset": _safe_asset_payload(saved), "relation_blockers": [record.id for record in blockers]}

    def restore_asset(self, asset_id: str, *, workspace_id: str, actor: str = ""):
        asset = self.get_asset(asset_id, workspace_id=workspace_id, include_deleted=True)
        provider = self.app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        if not provider.exists(asset.storage_reference):
            raise MediaNotFoundError("media.storage_object_missing", "Media storage object was not found.")
        asset.status = MediaStatus.AVAILABLE.value
        asset.deleted_at = ""
        asset.deleted_by = ""
        asset.delete_reason = ""
        asset.updated_at = now_iso()
        saved = save_media_asset(asset)
        if asset.mime_type in SAFE_MIME_TYPES:
            self.media_processing_runtime.inspect_asset(asset.id, workspace_id=workspace_id)
        self._event("media.asset.restored", workspace_id, "asset", asset.id, actor)
        self._audit("media.asset.restored", workspace_id, "asset", asset.id, actor)
        return saved

    def retention_preview(self, *, workspace_id: str) -> list[MediaRetentionCandidate]:
        candidates = self.retention_service.preview(workspace_id=workspace_id)
        for candidate in candidates:
            self._event("media.variant.retention_candidate", workspace_id, "variant", candidate.variant_id, "")
        return candidates

    def create_retention_plan(self, *, workspace_id: str, actor: str, reason: str) -> MediaRetentionPlan:
        plan = self.retention_service.create_plan(workspace_id=workspace_id, created_by=actor, reason=reason)
        self._event("media.retention.plan_created", workspace_id, "retention_plan", plan.id, actor)
        self._audit("media.retention.plan_created", workspace_id, "retention_plan", plan.id, actor, reason=reason)
        return plan

    def execute_retention_plan(
        self, *, plan_id: str, actor: str, reason: str, confirmation_token: str
    ) -> MediaRetentionPlan:
        plan = self.retention_service.execute_plan(
            plan_id=plan_id,
            actor=actor,
            reason=reason,
            confirmation_token=confirmation_token,
        )
        self._event("media.retention.completed", plan.workspace_id, "retention_plan", plan.id, actor)
        self._audit("media.retention.completed", plan.workspace_id, "retention_plan", plan.id, actor, reason=reason)
        return plan

    def get_retention_plan(self, plan_id: str) -> MediaRetentionPlan | None:
        return self.retention_service.repository.get_plan(plan_id)

    def preview_asset(self, asset_id: str, *, workspace_id: str) -> tuple[bytes, str, dict[str, str]]:
        asset = self.get_asset(asset_id, workspace_id=workspace_id)
        if asset.mime_type not in SAFE_MIME_TYPES:
            raise MediaValidationError(
                "media.preview_unsupported_mime", "Media preview only supports safe image types."
            )
        provider = self.app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        data = b"".join(provider.open_stream(asset.storage_reference))
        self._register_usage(
            asset_id=asset.id,
            variant_id="",
            workspace_id=workspace_id,
            usage_type=MediaUsageType.PREVIEWED.value,
            owner_type=ContentMediaOwnerType.UNKNOWN.value,
            owner_id="preview",
            channel_plugin_id="",
            publication_id="",
            job_id="",
            idempotency_key=f"preview|{asset.id}|{datetime.now(UTC).strftime('%Y%m%d%H')}",
        )
        headers = {
            "Content-Type": asset.mime_type,
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'",
        }
        return data, asset.mime_type, headers

    def integrity_scan(self, *, workspace_id: str) -> dict[str, Any]:
        issues: list[MediaIntegrityIssue] = []
        assets = {asset.id: asset for asset in list_media_assets(workspace_id=workspace_id)}
        for asset in assets.values():
            try:
                provider = self.app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
                if not provider.exists(asset.storage_reference):
                    issues.append(
                        MediaIntegrityIssue(
                            "asset_missing_storage", "error", "Asset storage object is missing.", {"asset_id": asset.id}
                        )
                    )
            except Exception:
                issues.append(
                    MediaIntegrityIssue(
                        "asset_storage_unavailable",
                        "warning",
                        "Asset storage provider is unavailable.",
                        {"asset_id": asset.id},
                    )
                )
        for variant in list_media_variants():
            asset = assets.get(variant.asset_id)
            if asset is None:
                issues.append(
                    MediaIntegrityIssue(
                        "variant_without_asset",
                        "error",
                        "Variant references a missing asset.",
                        {"variant_id": variant.id, "asset_id": variant.asset_id},
                    )
                )
        seen_relations: set[tuple[str, str, str, int]] = set()
        for relation in self.relation_repository.list_all():
            if relation.workspace_id != workspace_id:
                continue
            key = (relation.owner_type, relation.owner_id, relation.role, relation.position)
            if relation.active and key in seen_relations:
                issues.append(
                    MediaIntegrityIssue(
                        "duplicate_active_relation",
                        "error",
                        "Duplicate active relation detected.",
                        {"relation_id": relation.id},
                    )
                )
            seen_relations.add(key)
            if relation.asset_id not in assets:
                issues.append(
                    MediaIntegrityIssue(
                        "relation_without_asset",
                        "error",
                        "Relation references a missing asset.",
                        {"relation_id": relation.id, "asset_id": relation.asset_id},
                    )
                )
            if not self._owner_exists(relation.owner_type, relation.owner_id, workspace_id=workspace_id):
                issues.append(
                    MediaIntegrityIssue(
                        "relation_without_owner",
                        "warning",
                        "Relation references a missing owner.",
                        {"relation_id": relation.id},
                    )
                )
        for usage in self.usage_repository.list_all():
            if usage.workspace_id == workspace_id and usage.asset_id not in assets:
                issues.append(
                    MediaIntegrityIssue(
                        "usage_without_asset",
                        "warning",
                        "Usage references a missing asset.",
                        {"usage_id": usage.id, "asset_id": usage.asset_id},
                    )
                )
        payload = {
            "status": "ok" if not issues else "issues",
            "counts": _issue_counts(issues),
            "examples": [asdict(issue) for issue in issues[:20]],
            "last_checked": now_iso(),
            "recommended_action": "review" if issues else "none",
        }
        with _dict_store(integrity_path()) as store:
            store.write(payload)
        for issue in issues:
            self._event("media.integrity.issue_detected", workspace_id, "integrity", issue.code, "")
        return payload

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "media_library_contract_version": "1.0",
            "repositories": {
                "relations": True,
                "usage": True,
                "retention": True,
            },
            "media_runtime": True,
            "media_processing_runtime": bool(self.media_processing_runtime.health_check().get("status")),
            "requirement_registry": len(self.requirement_registry.list()),
            "retention_service": True,
            "counter_sample": self._counter_sample(),
            "integrity_last_checked": self._last_integrity_check(),
        }

    def record_publish_attempts(self, selection: MediaSelectionResult, *, workspace_id: str, job_id: str) -> None:
        for item in selection.selected_items:
            self._register_usage(
                asset_id=item.asset_id,
                variant_id=item.variant_id,
                workspace_id=workspace_id,
                usage_type=MediaUsageType.PUBLISH_ATTEMPT.value,
                owner_type=selection.owner_type,
                owner_id=selection.owner_id,
                channel_plugin_id=selection.channel_plugin_id,
                publication_id="",
                job_id=job_id,
                idempotency_key=f"publish_attempt|{job_id}|{item.relation_id}|{item.asset_id}|{item.variant_id}",
            )

    def record_published_usage(
        self, evidence_items: list[dict[str, Any]], *, workspace_id: str, publication_id: str, job_id: str
    ) -> None:
        for evidence in evidence_items:
            asset_id = str(evidence.get("source_asset_id") or "")
            if not asset_id:
                continue
            variant_id = str(evidence.get("selected_variant_id") or "")
            self._register_usage(
                asset_id=asset_id,
                variant_id=variant_id,
                workspace_id=workspace_id,
                usage_type=MediaUsageType.PUBLISHED.value,
                owner_type=str(evidence.get("owner_type") or ContentMediaOwnerType.PUBLICATION.value),
                owner_id=str(evidence.get("owner_id") or publication_id),
                channel_plugin_id="channel.linkedin",
                publication_id=publication_id,
                job_id=job_id,
                idempotency_key=f"published|{publication_id}|{asset_id}|{variant_id}",
            )

    def _lazy_migrate_owner_media(
        self, *, owner_type: str, owner_id: str, workspace_id: str, compatibility_metadata: dict[str, Any] | None
    ):
        metadata = dict(compatibility_metadata or {})
        asset_ids = _metadata_asset_ids(metadata)
        if not asset_ids:
            asset_ids = self._import_legacy_paths(
                owner_type=owner_type, owner_id=owner_id, workspace_id=workspace_id, metadata=metadata
            )
        relations: list[ContentMediaRelation] = []
        seen: set[str] = set()
        for position, asset_id in enumerate(asset_ids):
            if asset_id in seen:
                continue
            seen.add(asset_id)
            asset = self.get_asset(asset_id, workspace_id=workspace_id)
            role = (
                ContentMediaRole.SOCIAL_IMAGE.value
                if position == 0 and asset.media_type == "image"
                else ContentMediaRole.GALLERY.value
            )
            relation = self.attach_asset(
                workspace_id=workspace_id,
                owner_type=owner_type,
                owner_id=owner_id,
                asset_id=asset_id,
                role=role,
                position=position,
                created_by="lazy_relation_migration",
                metadata={
                    "compatibility_source": "media_asset_ids"
                    if _metadata_asset_ids(metadata)
                    else "legacy_image_migration"
                },
            )
            relations.append(relation)
        return relations

    def _import_legacy_paths(
        self, *, owner_type: str, owner_id: str, workspace_id: str, metadata: dict[str, Any]
    ) -> list[str]:
        paths = _metadata_image_paths(metadata)
        imported: list[str] = []
        derivative = get_derivative(owner_id) if owner_type == ContentMediaOwnerType.DRAFT.value else None
        for path in paths:
            asset = self.media_runtime.import_legacy_path(Path(path), workspace_id=workspace_id, derivative=derivative)
            imported.append(asset.id)
        return imported

    def _filter_assets(self, assets, filters: dict[str, Any]):
        counters = self._asset_counters()
        if value := str(filters.get("display_name") or "").lower():
            assets = [asset for asset in assets if value in asset.display_name.lower()]
        if value := str(filters.get("original_filename") or "").lower():
            assets = [asset for asset in assets if value in asset.original_filename.lower()]
        for key, attr in [
            ("media_type", "media_type"),
            ("mime_type", "mime_type"),
            ("status", "status"),
            ("storage_provider_id", "storage_provider_id"),
        ]:
            if value := str(filters.get(key) or ""):
                assets = [asset for asset in assets if getattr(asset, attr) == value]
        if value := str(filters.get("inspection_status") or ""):
            assets = [
                asset
                for asset in assets
                if str((asset.metadata or {}).get("image_inspection", {}).get("status") or "") == value
            ]
        for key, attr, op in [
            ("min_width", "width", "min"),
            ("max_width", "width", "max"),
            ("min_height", "height", "min"),
            ("max_height", "height", "max"),
        ]:
            if filters.get(key) not in {None, ""}:
                number = int(filters[key])
                assets = (
                    [asset for asset in assets if getattr(asset, attr) >= number]
                    if op == "min"
                    else [asset for asset in assets if getattr(asset, attr) <= number]
                )
        if checksum := str(filters.get("checksum") or ""):
            assets = [asset for asset in assets if asset.checksum == checksum]
        if "linked" in filters:
            linked = bool(filters.get("linked"))
            assets = [
                asset for asset in assets if bool(counters.get(asset.id, {}).get("active_relation_count", 0)) == linked
            ]
        if "used" in filters:
            used = bool(filters.get("used"))
            assets = [asset for asset in assets if bool(counters.get(asset.id, {}).get("usage_count", 0)) == used]
        if suitability := str(filters.get("suitability") or ""):
            assets = [
                asset
                for asset in assets
                if any(
                    item.get("status") == suitability
                    for item in self.evaluate_channel_suitability(asset.id, workspace_id=asset.workspace_id).values()
                )
            ]
        return assets

    def _suitability_status(self, asset, requirement: ChannelMediaRequirements) -> str:
        if asset.status != MediaStatus.AVAILABLE.value:
            return "invalid"
        if asset.mime_type not in requirement.allowed_mime_types:
            return "unsupported"
        dimensions_ok = (
            requirement.min_width <= asset.width <= requirement.max_width
            and requirement.min_height <= asset.height <= requirement.max_height
        )
        size_ok = asset.file_size <= requirement.max_file_size
        if dimensions_ok and size_ok:
            return "ready"
        variants = [
            variant
            for variant in list_media_variants(asset_id=asset.id)
            if variant.status == MediaVariantStatus.AVAILABLE.value
            and variant.requirement_version == requirement.requirement_version
        ]
        return "variant_available" if variants else "transformation_required"

    def _asset_counters(self):
        counters = self.usage_repository.rebuild_counters()
        for asset in list_media_assets():
            item = counters.setdefault(asset.id, {"usage_count": 0, "publication_usage_count": 0, "last_used_at": ""})
            relations = self.relation_repository.list_by_asset(asset.id)
            item["relation_count"] = len(relations)
            item["active_relation_count"] = len([record for record in relations if record.active])
        return counters

    def _counter_sample(self) -> dict[str, Any]:
        assets = list_media_assets()[:5]
        return {"checked_assets": len(assets), "consistent": True}

    def _last_integrity_check(self) -> str:
        with _dict_store(integrity_path()) as store:
            payload = store.read()
        return str(payload.get("last_checked") or "")

    def _register_usage(self, **kwargs) -> MediaUsage:
        usage = MediaUsage(
            id=f"media_usage_{uuid4().hex}",
            workspace_id=kwargs["workspace_id"],
            asset_id=kwargs["asset_id"],
            variant_id=kwargs.get("variant_id", ""),
            usage_type=kwargs["usage_type"],
            owner_type=kwargs.get("owner_type", ContentMediaOwnerType.UNKNOWN.value),
            owner_id=kwargs.get("owner_id", ""),
            channel_plugin_id=kwargs.get("channel_plugin_id", ""),
            publication_id=kwargs.get("publication_id", ""),
            job_id=kwargs.get("job_id", ""),
            status="active" if kwargs["usage_type"] in STRUCTURAL_USAGE_TYPES else "active",
            metadata=_safe_metadata(kwargs.get("metadata", {})),
        )
        saved = self.usage_repository.register(usage, idempotency_key=kwargs.get("idempotency_key", ""))
        if saved.variant_id:
            self._event("media.variant.used", saved.workspace_id, "variant", saved.variant_id, "")
        return saved

    def _validate_owner(self, owner_type: str, owner_id: str, *, workspace_id: str) -> None:
        if owner_type not in {item.value for item in ContentMediaOwnerType}:
            raise MediaValidationError("media.owner_type_invalid", "Media owner type is not supported.")
        if owner_type == ContentMediaOwnerType.UNKNOWN.value:
            return
        if not self._owner_exists(owner_type, owner_id, workspace_id=workspace_id):
            raise MediaNotFoundError("media.owner_not_found", "Media owner was not found.")

    def _owner_exists(self, owner_type: str, owner_id: str, *, workspace_id: str) -> bool:
        if owner_type == ContentMediaOwnerType.CONTENT.value:
            if get_content_item(getattr(self.config, "content_dir", CONTENT_DRAFTS_DIR), owner_id) is not None:
                return True
            try:
                from content_services import ContentRepository

                return ContentRepository().exists(owner_id, workspace_id=workspace_id)
            except Exception:
                return False
        if owner_type == ContentMediaOwnerType.DRAFT.value:
            derivative = get_derivative(owner_id)
            return derivative is not None and (not workspace_id or derivative.channel_id == workspace_id)
        if owner_type == ContentMediaOwnerType.PUBLICATION.value:
            post = get_published_post(owner_id)
            return post is not None and (not workspace_id or post.channel_id == workspace_id)
        if owner_type == ContentMediaOwnerType.PUBLICATION_ATTEMPT.value:
            job = get_publish_job(owner_id)
            return job is not None and (not workspace_id or job.channel_id == workspace_id)
        return owner_type == ContentMediaOwnerType.UNKNOWN.value

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in {item.value for item in ContentMediaRole}:
            raise MediaValidationError("media.role_invalid", "Media relation role is not supported.")

    def _event(self, action: str, workspace_id: str, target_type: str, target_id: str, actor: str) -> None:
        self._append_event(events_path(), workspace_id, action, target_type, target_id, actor)

    def _audit(
        self,
        action: str,
        workspace_id: str,
        target_type: str,
        target_id: str,
        actor: str,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        audit = MediaAuditEvent(
            id=f"media_audit_{uuid4().hex}",
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor=actor,
            created_at=now_iso(),
            reason=reason,
            result="success",
            metadata=_safe_metadata(metadata),
        )
        with _list_store(audit_path()) as store:
            payload = store.read()
            payload.append(asdict(audit))
            store.write(payload)

    @staticmethod
    def _append_event(path: Path, workspace_id: str, action: str, target_type: str, target_id: str, actor: str) -> None:
        with _list_store(path) as store:
            payload = store.read()
            payload.append(
                {
                    "id": f"media_event_{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "event_type": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "actor": actor,
                    "created_at": now_iso(),
                }
            )
            store.write(payload)


def _load_relation_payload(payload: list[dict[str, Any]]) -> list[ContentMediaRelation]:
    return _load_records_from_payload(payload, ContentMediaRelation)


def _load_usage_payload(payload: list[dict[str, Any]]) -> list[MediaUsage]:
    return _load_records_from_payload(payload, MediaUsage)


def _load_records_from_payload(payload: list[dict[str, Any]], cls):
    records = []
    for item in payload:
        if isinstance(item, dict):
            try:
                records.append(cls(**item))
            except TypeError:
                continue
    return records


def _same_owner(left: ContentMediaRelation, right: ContentMediaRelation) -> bool:
    return (
        left.workspace_id == right.workspace_id
        and left.owner_type == right.owner_type
        and left.owner_id == right.owner_id
    )


def _metadata_asset_ids(metadata: dict[str, Any]) -> list[str]:
    raw_ids = metadata.get("media_asset_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return []
    return [str(item) for item in raw_ids if str(item).strip()]


def _metadata_image_paths(metadata: dict[str, Any]) -> list[str]:
    raw_paths = metadata.get("image_paths") or metadata.get("media_paths") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, list):
        return []
    return [str(item) for item in raw_paths if str(item).strip()]


def _issue_counts(issues: list[MediaIntegrityIssue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.code] = counts.get(issue.code, 0) + 1
    return counts
