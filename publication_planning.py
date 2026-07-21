from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import channel_store
from channel_models import ContentDerivative, PublishJob
from channel_storage import locked_json_store
from content_services import ContentService, _canonical_json
from src.core.content import (
    PUBLICATION_PLAN_CONTRACT_VERSION,
    PUBLICATION_TARGET_CONTRACT_VERSION,
    ChannelContentVariant,
    ContentAuditEvent,
    ContentIntegrityIssue,
    ContentNotFoundError,
    ContentValidationError,
    PublicationPlan,
    PublicationPlanStatus,
    PublicationTarget,
    PublicationTargetStatus,
)

T = TypeVar("T")


def _path(name: str) -> Path:
    return channel_store.STUDIO_DATA_DIR / name


def publication_plans_path() -> Path:
    return _path("publication_plans.json")


def publication_targets_path() -> Path:
    return _path("publication_targets.json")


def publication_events_path() -> Path:
    return _path("publication_planning_events.json")


def publication_audit_path() -> Path:
    return _path("publication_planning_audit.json")


def publication_integrity_path() -> Path:
    return _path("publication_planning_integrity_last_scan.json")


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _known_fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _load_records(path: Path, cls: type[T]) -> list[T]:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
    records: list[T] = []
    allowed = _known_fields(cls)
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
        except TypeError:
            continue
    return records


def _mutate_records(  # noqa: UP047
    path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]
) -> Any:
    with _list_store(path) as store:
        payload = store.read()
        allowed = _known_fields(cls)
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


def _channel_id(channel_plugin_id: str) -> str:
    return channel_plugin_id.removeprefix("channel.") if channel_plugin_id.startswith("channel.") else channel_plugin_id


def _safe_preview(value: str, limit: int = 280) -> str:
    normalized = value.replace("\r\n", "\n").strip()
    return normalized if len(normalized) <= limit else normalized[:limit].rstrip() + "..."


def snapshot_checksum(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


class PublicationPlanRepository:
    def create(self, plan: PublicationPlan) -> PublicationPlan:
        def mutate(records: list[PublicationPlan]):
            if any(record.id == plan.id for record in records):
                raise ContentValidationError("publication.plan_exists", "Publication plan already exists.")
            records.append(plan)
            return True, plan

        return _mutate_records(publication_plans_path(), PublicationPlan, mutate)

    def save(self, plan: PublicationPlan) -> PublicationPlan:
        def mutate(records: list[PublicationPlan]):
            for index, record in enumerate(records):
                if record.id == plan.id:
                    records[index] = plan
                    return True, plan
            records.append(plan)
            return True, plan

        return _mutate_records(publication_plans_path(), PublicationPlan, mutate)

    def get(self, plan_id: str) -> PublicationPlan | None:
        return next((record for record in self.list_all() if record.id == plan_id), None)

    def list_all(self, *, workspace_id: str = "") -> list[PublicationPlan]:
        records = _load_records(publication_plans_path(), PublicationPlan)
        if workspace_id:
            records = [record for record in records if record.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.updated_at or item.created_at, item.id), reverse=True)


class PublicationTargetRepository:
    def create(self, target: PublicationTarget) -> PublicationTarget:
        def mutate(records: list[PublicationTarget]):
            for record in records:
                if record.id == target.id:
                    raise ContentValidationError("publication.target_exists", "Publication target already exists.")
                if (
                    record.publication_plan_id == target.publication_plan_id
                    and record.channel_plugin_id == target.channel_plugin_id
                    and record.channel_account_id == target.channel_account_id
                    and record.capability == target.capability
                    and record.position == target.position
                    and record.status != PublicationTargetStatus.CANCELLED.value
                ):
                    raise ContentValidationError("publication.target_duplicate", "Duplicate publication target.")
            records.append(target)
            return True, target

        return _mutate_records(publication_targets_path(), PublicationTarget, mutate)

    def save(self, target: PublicationTarget) -> PublicationTarget:
        def mutate(records: list[PublicationTarget]):
            for index, record in enumerate(records):
                if record.id == target.id:
                    records[index] = target
                    return True, target
            records.append(target)
            return True, target

        return _mutate_records(publication_targets_path(), PublicationTarget, mutate)

    def get(self, target_id: str) -> PublicationTarget | None:
        return next((record for record in self.list_all() if record.id == target_id), None)

    def list_all(self, *, workspace_id: str = "") -> list[PublicationTarget]:
        records = _load_records(publication_targets_path(), PublicationTarget)
        if workspace_id:
            records = [record for record in records if record.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.publication_plan_id, item.position, item.id))

    def list_by_plan(self, plan_id: str) -> list[PublicationTarget]:
        return [record for record in self.list_all() if record.publication_plan_id == plan_id]


class PublicationPlanningService:
    def __init__(self, *, app_runtime, config, content_service: ContentService | None = None) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.content_service = content_service or app_runtime.content_service(config)
        self.media_library_service = app_runtime.media_library_service(config)
        self.plan_repository = PublicationPlanRepository()
        self.target_repository = PublicationTargetRepository()

    def create_plan(
        self,
        *,
        workspace_id: str,
        content_item_id: str,
        name: str,
        created_by: str = "",
        planned_start_at: str = "",
        timezone: str = "UTC",
        notes: str = "",
        follow_current_revision: bool = False,
    ) -> PublicationPlan:
        item = self.content_service.get_content(content_item_id, workspace_id=workspace_id)
        plan = PublicationPlan(
            id=f"publication_plan_{uuid4().hex}",
            workspace_id=workspace_id,
            content_item_id=item.id,
            source_revision_id=item.current_revision_id,
            name=name.strip() or item.title,
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
            created_by=created_by,
            updated_by=created_by,
            planned_start_at=planned_start_at,
            timezone=timezone or "UTC",
            notes=notes,
            metadata={"revision_policy": "follow_current_revision" if follow_current_revision else "pinned_revision"},
        )
        saved = self.plan_repository.create(plan)
        self._event("publication.plan.created", workspace_id, "publication_plan", saved.id, created_by)
        self._audit("plan.create", workspace_id, "publication_plan", saved.id, created_by)
        return saved

    def add_target(
        self,
        plan_id: str,
        *,
        workspace_id: str,
        channel_plugin_id: str,
        channel_account_id: str,
        capability: str,
        channel_variant_id: str = "",
        media_relation_ids: list[str] | None = None,
        scheduled_at: str = "",
        timezone: str = "UTC",
        position: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> PublicationTarget:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        target = PublicationTarget(
            id=f"publication_target_{uuid4().hex}",
            publication_plan_id=plan.id,
            workspace_id=workspace_id,
            channel_plugin_id=channel_plugin_id,
            channel_account_id=channel_account_id,
            capability=capability,
            source_revision_id=plan.source_revision_id,
            channel_variant_id=channel_variant_id,
            media_relation_ids=list(media_relation_ids or []),
            position=max(position, 0),
            scheduled_at=scheduled_at,
            timezone=timezone or plan.timezone or "UTC",
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
            metadata=dict(metadata or {}),
        )
        saved = self.target_repository.create(target)
        self._audit("target.add", workspace_id, "publication_target", saved.id, "")
        return saved

    def update_target(self, target_id: str, *, workspace_id: str, actor: str = "", **updates) -> PublicationTarget:
        target = self._get_target(target_id, workspace_id=workspace_id)
        for key in (
            "channel_account_id",
            "capability",
            "channel_variant_id",
            "scheduled_at",
            "timezone",
            "status",
        ):
            if key in updates:
                setattr(target, key, str(updates[key] or ""))
        if "media_relation_ids" in updates and isinstance(updates["media_relation_ids"], list):
            target.media_relation_ids = [str(item) for item in updates["media_relation_ids"]]
        if "position" in updates:
            target.position = max(int(updates["position"] or 0), 0)
        target.updated_at = channel_store.now_iso()
        target.snapshot_checksum = (
            "" if target.status in {PublicationTargetStatus.DRAFT.value, ""} else target.snapshot_checksum
        )
        saved = self.target_repository.save(target)
        self._audit("target.update", workspace_id, "publication_target", saved.id, actor)
        return saved

    def validate_plan(self, plan_id: str, *, workspace_id: str) -> dict[str, Any]:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        target_results = [
            self.validate_target(target.id, workspace_id=workspace_id)
            for target in self.target_repository.list_by_plan(plan.id)
        ]
        valid = bool(target_results) and all(result["valid"] for result in target_results)
        plan.validation_status = "valid" if valid else "invalid"
        plan.status = PublicationPlanStatus.READY.value if valid else PublicationPlanStatus.BLOCKED.value
        plan.updated_at = channel_store.now_iso()
        self.plan_repository.save(plan)
        self._event("publication.plan.validated", workspace_id, "publication_plan", plan.id, "")
        return {"valid": valid, "plan_id": plan.id, "targets": target_results}

    def validate_target(self, target_id: str, *, workspace_id: str) -> dict[str, Any]:
        target = self._get_target(target_id, workspace_id=workspace_id)
        plan = self._get_plan(target.publication_plan_id, workspace_id=workspace_id)
        violations: list[dict[str, str]] = []
        try:
            revision, variant, content_result = self.content_service.resolve_channel_content(
                content_item_id=plan.content_item_id,
                workspace_id=workspace_id,
                channel_plugin_id=target.channel_plugin_id,
                capability=target.capability,
                source_revision_id=target.source_revision_id,
                channel_variant_id=target.channel_variant_id,
            )
            violations.extend(asdict(item) for item in content_result.violations)
        except Exception as exc:
            revision = None
            variant = None
            content_result = None
            violations.append(
                {"code": getattr(exc, "code", "content_resolution_failed"), "message": str(exc), "field": "content"}
            )
        if not channel_store.get_channel_connection(_channel_id(target.channel_plugin_id)):
            violations.append(
                {
                    "code": "account_missing",
                    "message": "Channel account is not configured.",
                    "field": "channel_account_id",
                }
            )
        media = self._resolve_media(plan, target, workspace_id=workspace_id)
        if media.get("errors"):
            violations.extend(media["errors"])
        if target.channel_plugin_id == "channel.mastodon":
            mastodon_requirements = self._mastodon_target_requirements(target)
            if mastodon_requirements.get("stale"):
                violations.append(
                    {
                        "code": "mastodon.requirements_stale",
                        "message": "Mastodon requirements snapshot is stale.",
                        "field": "requirements",
                    }
                )
            limit = int(
                mastodon_requirements.get("max_body_length") or mastodon_requirements.get("content_length_limit") or 0
            )
            resolved_body = (variant.body if variant else revision.body) if revision else ""
            if limit and len(resolved_body.replace("\r\n", "\n").strip()) > limit:
                violations.append(
                    {
                        "code": "mastodon.body_too_long",
                        "message": "Body exceeds the Mastodon instance text limit.",
                        "field": "body",
                    }
                )
        valid = not violations
        target.validation_status = "valid" if valid else "invalid"
        target.status = PublicationTargetStatus.READY.value if valid else PublicationTargetStatus.INVALID.value
        target.updated_at = channel_store.now_iso()
        self.target_repository.save(target)
        return {
            "valid": valid,
            "target_id": target.id,
            "revision_id": revision.id if revision else "",
            "variant_id": variant.id if variant else "",
            "direct_use": bool(content_result.direct_use) if content_result else False,
            "requirement_version": content_result.requirement_version if content_result else "",
            "violations": violations,
            "media": media,
        }

    def prepare_plan(self, plan_id: str, *, workspace_id: str, actor: str = "") -> PublicationPlan:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        checksums: list[str] = []
        valid = True
        for target in self.target_repository.list_by_plan(plan.id):
            prepared = self.prepare_target(target.id, workspace_id=workspace_id, actor=actor)
            checksums.append(prepared.snapshot_checksum)
            valid = valid and prepared.status == PublicationTargetStatus.AWAITING_CONFIRMATION.value
        plan.snapshot_checksum = snapshot_checksum(
            {
                "contract_version": PUBLICATION_PLAN_CONTRACT_VERSION,
                "plan_id": plan.id,
                "target_checksums": checksums,
            }
        )
        plan.status = PublicationPlanStatus.READY.value if valid else PublicationPlanStatus.BLOCKED.value
        plan.validation_status = "valid" if valid else "invalid"
        plan.updated_at = channel_store.now_iso()
        saved = self.plan_repository.save(plan)
        self._event("publication.plan.prepared", workspace_id, "publication_plan", saved.id, actor)
        self._audit(
            "plan.prepare", workspace_id, "publication_plan", saved.id, actor, snapshot_checksum=saved.snapshot_checksum
        )
        return saved

    def prepare_target(self, target_id: str, *, workspace_id: str, actor: str = "") -> PublicationTarget:
        target = self._get_target(target_id, workspace_id=workspace_id)
        plan = self._get_plan(target.publication_plan_id, workspace_id=workspace_id)
        validation = self.validate_target(target.id, workspace_id=workspace_id)
        if not validation["valid"]:
            return self._mark_target(target, PublicationTargetStatus.INVALID.value)
        revision, variant, content_result = self.content_service.resolve_channel_content(
            content_item_id=plan.content_item_id,
            workspace_id=workspace_id,
            channel_plugin_id=target.channel_plugin_id,
            capability=target.capability,
            source_revision_id=target.source_revision_id,
            channel_variant_id=target.channel_variant_id,
        )
        media = self._resolve_media(plan, target, workspace_id=workspace_id)
        snapshot = self._build_snapshot(
            plan, target, revision=revision, variant=variant, content_result=content_result, media=media
        )
        if target.channel_plugin_id == "channel.mastodon":
            snapshot = snapshot | self._mastodon_snapshot_metadata(target)
        checksum = snapshot_checksum(snapshot)
        target.snapshot_checksum = checksum
        target.metadata = {**dict(target.metadata or {}), "snapshot": snapshot, "confirmation_required": True}
        target.status = PublicationTargetStatus.AWAITING_CONFIRMATION.value
        target.validation_status = "valid"
        target.updated_at = channel_store.now_iso()
        saved = self.target_repository.save(target)
        self._audit("target.prepare", workspace_id, "publication_target", saved.id, actor, snapshot_checksum=checksum)
        return saved

    def queue_target(
        self,
        target_id: str,
        *,
        workspace_id: str,
        actor: str = "",
        confirmation: bool = False,
        allow_stale: bool = False,
    ) -> PublicationTarget:
        target = self._get_target(target_id, workspace_id=workspace_id)
        if not confirmation:
            raise ContentValidationError("publication.confirmation_required", "Queueing requires confirmation.")
        if not target.snapshot_checksum:
            target = self.prepare_target(target.id, workspace_id=workspace_id, actor=actor)
        stale = self.is_target_stale(target.id, workspace_id=workspace_id)
        if stale["stale"] and not allow_stale:
            target.status = PublicationTargetStatus.STALE.value
            self.target_repository.save(target)
            raise ContentValidationError("publication.target_stale", "Publication target is stale.", stale)
        if target.job_id and channel_store.get_publish_job(target.job_id):
            return target
        plan = self._get_plan(target.publication_plan_id, workspace_id=workspace_id)
        derivative = self._save_derivative_for_target(plan, target)
        job = self._save_publish_job_for_target(target, derivative)
        target.job_id = job.id
        target.status = PublicationTargetStatus.QUEUED.value
        target.updated_at = channel_store.now_iso()
        saved = self.target_repository.save(target)
        self._event("publication.target.queued", workspace_id, "publication_target", target.id, actor)
        self._audit(
            "target.queue",
            workspace_id,
            "publication_target",
            saved.id,
            actor,
            snapshot_checksum=saved.snapshot_checksum,
        )
        self.refresh_status(plan.id, workspace_id=workspace_id)
        return saved

    def queue_plan(
        self, plan_id: str, *, workspace_id: str, actor: str = "", confirmation: bool = False
    ) -> PublicationPlan:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        for target in self.target_repository.list_by_plan(plan.id):
            self.queue_target(target.id, workspace_id=workspace_id, actor=actor, confirmation=confirmation)
        return self.refresh_status(plan.id, workspace_id=workspace_id)

    def cancel_plan(self, plan_id: str, *, workspace_id: str, actor: str = "") -> PublicationPlan:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        plan.status = PublicationPlanStatus.CANCELLED.value
        plan.updated_at = channel_store.now_iso()
        for target in self.target_repository.list_by_plan(plan.id):
            if target.status not in {PublicationTargetStatus.PUBLISHED.value, PublicationTargetStatus.RUNNING.value}:
                target.status = PublicationTargetStatus.CANCELLED.value
                target.updated_at = channel_store.now_iso()
                self.target_repository.save(target)
        saved = self.plan_repository.save(plan)
        self._event("publication.plan.cancelled", workspace_id, "publication_plan", plan.id, actor)
        self._audit("plan.cancel", workspace_id, "publication_plan", saved.id, actor)
        return saved

    def refresh_status(self, plan_id: str, *, workspace_id: str) -> PublicationPlan:
        plan = self._get_plan(plan_id, workspace_id=workspace_id)
        targets = self.target_repository.list_by_plan(plan.id)
        statuses = {target.status for target in targets}
        if statuses and statuses <= {PublicationTargetStatus.QUEUED.value}:
            plan.status = PublicationPlanStatus.QUEUED.value
        elif PublicationTargetStatus.QUEUED.value in statuses:
            plan.status = PublicationPlanStatus.PARTIALLY_QUEUED.value
        elif statuses and statuses <= {PublicationTargetStatus.PUBLISHED.value}:
            plan.status = PublicationPlanStatus.COMPLETED.value
        plan.updated_at = channel_store.now_iso()
        return self.plan_repository.save(plan)

    def is_target_stale(self, target_id: str, *, workspace_id: str) -> dict[str, Any]:
        target = self._get_target(target_id, workspace_id=workspace_id)
        snapshot = dict((target.metadata or {}).get("snapshot") or {})
        reasons: list[str] = []
        if not snapshot:
            return {"stale": True, "reasons": ["snapshot_missing"]}
        plan = self._get_plan(target.publication_plan_id, workspace_id=workspace_id)
        item = self.content_service.get_content(plan.content_item_id, workspace_id=workspace_id)
        revision_policy = dict(plan.metadata or {}).get("revision_policy", "pinned_revision")
        if revision_policy == "follow_current_revision" and item.current_revision_id != snapshot.get("revision_id"):
            reasons.append("current_revision_changed")
        revision = self.content_service.revision_repository.get(str(snapshot.get("revision_id") or ""))
        if revision is None or revision.checksum != snapshot.get("revision_checksum"):
            reasons.append("revision_checksum_changed")
        variant_id = str(snapshot.get("variant_id") or "")
        if variant_id:
            variant = self.content_service.variant_repository.get(variant_id)
            if (
                variant is None
                or variant.status == "archived"
                or variant.variant_checksum != snapshot.get("variant_checksum")
            ):
                reasons.append("variant_changed")
        for relation_id in snapshot.get("media_relation_ids") or []:
            relation = self.media_library_service.relation_repository.get(str(relation_id))
            if relation is None or not relation.active:
                reasons.append("media_relation_changed")
                break
        if target.channel_plugin_id == "channel.mastodon":
            mastodon_requirements = self._mastodon_target_requirements(target)
            if mastodon_requirements.get("stale"):
                reasons.append("mastodon_requirements_stale")
            if snapshot.get("mastodon_requirements_checksum") and mastodon_requirements.get(
                "requirement_version"
            ) != snapshot.get("mastodon_requirements_checksum"):
                reasons.append("mastodon_requirements_changed")
        recalculated = snapshot_checksum(snapshot)
        if recalculated != target.snapshot_checksum:
            reasons.append("snapshot_checksum_mismatch")
        return {"stale": bool(reasons), "reasons": reasons}

    def scan_integrity(self, *, workspace_id: str = "") -> list[ContentIntegrityIssue]:
        issues: list[ContentIntegrityIssue] = []
        plans = self.plan_repository.list_all(workspace_id=workspace_id)
        targets = self.target_repository.list_all(workspace_id=workspace_id)
        plan_ids = {plan.id for plan in plans}
        for target in targets:
            if target.publication_plan_id not in plan_ids:
                issues.append(
                    ContentIntegrityIssue(
                        "publication.target_without_plan",
                        "Publication target points to a missing plan.",
                        1,
                        ({"target_id": target.id},),
                    )
                )
            if target.status == PublicationTargetStatus.QUEUED.value and not target.job_id:
                issues.append(
                    ContentIntegrityIssue(
                        "publication.queued_target_without_job",
                        "Queued target has no job.",
                        1,
                        ({"target_id": target.id},),
                    )
                )
        with _dict_store(publication_integrity_path()) as store:
            store.write({"checked_at": channel_store.now_iso(), "issues": [asdict(issue) for issue in issues]})
        return issues

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "repositories": {"plans": True, "targets": True},
            "content_service": self.content_service.health_check().get("status", "unknown"),
            "media_library": bool(self.media_library_service),
            "job_infrastructure": True,
        }

    def _resolve_media(self, plan: PublicationPlan, target: PublicationTarget, *, workspace_id: str) -> dict[str, Any]:
        try:
            resolution = self.media_library_service.resolve_owner_media(
                owner_type="content",
                owner_id=plan.content_item_id,
                workspace_id=workspace_id,
                channel_plugin_id=target.channel_plugin_id,
                capability="linkedin.image_publish"
                if target.channel_plugin_id == "channel.linkedin"
                else target.capability,
            )
        except Exception as exc:
            return {
                "selected": [],
                "errors": [
                    {"code": getattr(exc, "code", "media_resolution_failed"), "message": str(exc), "field": "media"}
                ],
            }
        selected = list(resolution.selected_items)
        if target.media_relation_ids:
            wanted = set(target.media_relation_ids)
            selected = [item for item in selected if item.relation_id in wanted]
        return {
            "selected": [asdict(item) for item in selected],
            "media_requirement_version": resolution.requirement_version,
            "warnings": list(resolution.warnings),
            "errors": [asdict(item) for item in resolution.rejected_items],
        }

    def _build_snapshot(
        self,
        plan: PublicationPlan,
        target: PublicationTarget,
        *,
        revision,
        variant: ChannelContentVariant | None,
        content_result,
        media: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "contract_version": PUBLICATION_TARGET_CONTRACT_VERSION,
            "content_item_id": plan.content_item_id,
            "revision_id": revision.id,
            "revision_checksum": revision.checksum,
            "variant_id": variant.id if variant else "",
            "variant_checksum": variant.variant_checksum if variant else "",
            "content_requirement_version": content_result.requirement_version,
            "media_relation_ids": [item["relation_id"] for item in media.get("selected", [])],
            "resolved_asset_ids": [item["asset_id"] for item in media.get("selected", [])],
            "resolved_variant_ids": [
                item["variant_id"] for item in media.get("selected", []) if item.get("variant_id")
            ],
            "media_requirement_version": media.get("media_requirement_version", ""),
            "channel_account_id": target.channel_account_id,
            "channel_plugin_id": target.channel_plugin_id,
            "capability": target.capability,
            "scheduled_at": target.scheduled_at,
            "timezone": target.timezone,
        }

    def _mastodon_target_requirements(self, target: PublicationTarget) -> dict[str, Any]:
        try:
            runtime = self.app_runtime.get_plugin_service("channel.mastodon", "channel_runtime")
            return runtime.resolve_content_requirements(channel_account_id=target.channel_account_id)
        except Exception:
            return {"stale": True, "safe_error_code": "mastodon.requirements_unavailable"}

    def _mastodon_snapshot_metadata(self, target: PublicationTarget) -> dict[str, Any]:
        try:
            runtime = self.app_runtime.get_plugin_service("channel.mastodon", "channel_runtime")
            content_req = runtime.resolve_content_requirements(channel_account_id=target.channel_account_id)
            media_req = runtime.resolve_media_requirements(channel_account_id=target.channel_account_id)
        except Exception:
            return {"mastodon_requirements_stale": True}
        return {
            "mastodon_requirements_checksum": str(
                content_req.get("requirement_version") or media_req.get("requirement_version") or ""
            ),
            "mastodon_content_requirements": content_req,
            "mastodon_media_requirements": media_req,
            "mastodon_options": dict((target.metadata or {}).get("mastodon_options") or {}),
        }

    def _save_derivative_for_target(self, plan: PublicationPlan, target: PublicationTarget) -> ContentDerivative:
        snapshot = dict((target.metadata or {}).get("snapshot") or {})
        revision, variant, _result = self.content_service.resolve_channel_content(
            content_item_id=plan.content_item_id,
            workspace_id=plan.workspace_id,
            channel_plugin_id=target.channel_plugin_id,
            capability=target.capability,
            source_revision_id=target.source_revision_id,
            channel_variant_id=target.channel_variant_id,
        )
        title = variant.title if variant else revision.title
        body = variant.body if variant else revision.body
        metadata = {
            "publication_plan_id": plan.id,
            "publication_target_id": target.id,
            "content_item_id": plan.content_item_id,
            "content_revision_id": revision.id,
            "revision_checksum": revision.checksum,
            "channel_variant_id": variant.id if variant else "",
            "variant_checksum": variant.variant_checksum if variant else "",
            "snapshot_checksum": target.snapshot_checksum,
            "snapshot": snapshot,
            "media_relation_ids": snapshot.get("media_relation_ids", []),
            "media_asset_ids": snapshot.get("resolved_asset_ids", []),
            "content_requirement_version": snapshot.get("content_requirement_version", ""),
            "media_requirement_version": snapshot.get("media_requirement_version", ""),
            "scheduled_at": target.scheduled_at,
            "planned_from_content_framework": True,
        }
        derivative = ContentDerivative(
            id=f"derivative_plan_{target.id}",
            source_document_id=plan.content_item_id,
            channel_id=_channel_id(target.channel_plugin_id),
            output_type="linkedin_post" if target.channel_plugin_id == "channel.linkedin" else target.capability,
            title=title,
            body=body,
            status="approved",
            generation_metadata_json=metadata,
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
        )
        return channel_store.save_derivative(derivative)

    def _save_publish_job_for_target(self, target: PublicationTarget, derivative: ContentDerivative) -> PublishJob:
        requested_at = target.scheduled_at or channel_store.now_iso()
        idempotency_key = hashlib.sha256(
            f"{target.id}|{target.snapshot_checksum}|{target.channel_account_id}|{target.capability}|{requested_at}".encode()
        ).hexdigest()
        for job in channel_store.list_publish_jobs(channel_id=derivative.channel_id, derivative_id=derivative.id):
            if job.result_details_json.get("planning_idempotency_key") == idempotency_key:
                return job
        job = PublishJob(
            id=f"publish_{uuid4().hex}",
            derivative_id=derivative.id,
            channel_id=derivative.channel_id,
            status="queued",
            requested_at=requested_at,
            last_step="queued_from_publication_plan",
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
            run_mode=str((target.metadata or {}).get("run_mode") or "dry_run"),
            result_details_json={
                "planning_idempotency_key": idempotency_key,
                "publication_target_id": target.id,
                "snapshot_checksum": target.snapshot_checksum,
                "snapshot_preview": {
                    "content_item_id": derivative.source_document_id,
                    "body_preview": _safe_preview(derivative.body),
                },
            },
        )
        return channel_store.save_publish_job(job)

    def _mark_target(self, target: PublicationTarget, status: str) -> PublicationTarget:
        target.status = status
        target.updated_at = channel_store.now_iso()
        return self.target_repository.save(target)

    def _get_plan(self, plan_id: str, *, workspace_id: str) -> PublicationPlan:
        plan = self.plan_repository.get(plan_id)
        if plan is None or (workspace_id and plan.workspace_id != workspace_id):
            raise ContentNotFoundError("publication.plan_not_found", "Publication plan was not found.")
        return plan

    def _get_target(self, target_id: str, *, workspace_id: str) -> PublicationTarget:
        target = self.target_repository.get(target_id)
        if target is None or (workspace_id and target.workspace_id != workspace_id):
            raise ContentNotFoundError("publication.target_not_found", "Publication target was not found.")
        return target

    def _event(self, action: str, workspace_id: str, target_type: str, target_id: str, actor: str) -> None:
        with _list_store(publication_events_path()) as store:
            records = store.read()
            records.append(
                {
                    "id": f"publication_event_{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "action": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "actor": actor,
                    "created_at": channel_store.now_iso(),
                }
            )
            store.write(records)

    def _audit(
        self,
        action: str,
        workspace_id: str,
        target_type: str,
        target_id: str,
        actor: str,
        *,
        reason: str = "",
        snapshot_checksum: str = "",
    ) -> None:
        audit = ContentAuditEvent(
            id=f"publication_audit_{uuid4().hex}",
            workspace_id=workspace_id,
            action=action,
            target_id=target_id,
            target_type=target_type,
            actor=actor,
            reason=reason,
            snapshot_checksum=snapshot_checksum,
            created_at=channel_store.now_iso(),
        )
        with _list_store(publication_audit_path()) as store:
            records = store.read()
            records.append(asdict(audit))
            store.write(records)
