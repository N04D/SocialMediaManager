from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import channel_store
from channel_storage import locked_json_store
from content_store import CONTENT_DRAFTS_DIR, get_content_item, plain_text_from_markdown
from src.core.content import (
    CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION,
    CONTENT_FRAMEWORK_VERSION,
    CONTENT_ITEM_CONTRACT_VERSION,
    CONTENT_REQUIREMENTS_CONTRACT_VERSION,
    CONTENT_REVISION_CONTRACT_VERSION,
    Campaign,
    ChannelContentRequirements,
    ChannelContentVariant,
    ChannelContentVariantStatus,
    ChannelContentVariantType,
    ClipCandidate,
    ContentAuditEvent,
    ContentConflictError,
    ContentIntegrityIssue,
    ContentItem,
    ContentNotFoundError,
    ContentRequirementResult,
    ContentRequirementViolation,
    ContentRevision,
    ContentStatus,
    ContentType,
    ContentValidationError,
    Entity,
    Outcome,
    Playbook,
    PolicyRule,
    ProvenanceRecord,
    Relationship,
    TimelineSegment,
    TransformationContract,
    TransformationRun,
)

T = TypeVar("T")

FORBIDDEN_METADATA_KEYS = {
    "storage_reference",
    "storage_ref",
    "local_path",
    "materialized_path",
    "object_path",
    "transfer_path",
    "absolute_path",
    "provider_secret",
    "provider_details",
}


def _path(name: str) -> Path:
    return channel_store.STUDIO_DATA_DIR / name


def entities_path() -> Path:
    return _path("content_entities.json")


def relationships_path() -> Path:
    return _path("content_relationships.json")


def transformation_runs_path() -> Path:
    return _path("content_transformation_runs.json")


def campaigns_path() -> Path:
    return _path("content_campaigns.json")


def outcomes_path() -> Path:
    return _path("content_outcomes.json")


def playbooks_path() -> Path:
    return _path("content_playbooks.json")


def policies_path() -> Path:
    return _path("content_policies.json")


def content_items_path() -> Path:
    return _path("content_items.json")


def content_revisions_path() -> Path:
    return _path("content_revisions.json")


def channel_variants_path() -> Path:
    return _path("channel_content_variants.json")


def migration_mappings_path() -> Path:
    return _path("content_migration_mappings.json")


def content_audit_path() -> Path:
    return _path("content_audit_events.json")


def content_events_path() -> Path:
    return _path("content_events.json")


def content_integrity_path() -> Path:
    return _path("content_integrity_last_scan.json")


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


def _write_records(path: Path, records: list[Any]) -> None:
    with _list_store(path) as store:
        store.write([asdict(record) for record in records])


def _mutate_records(  # noqa: UP047
    path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]
) -> Any:
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
        changed, result = mutator(records)
        if changed:
            store.write([asdict(record) for record in records])
        return result


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        lowered = str(key).lower()
        if lowered in FORBIDDEN_METADATA_KEYS or "path" in lowered or "reference" in lowered:
            continue
        if isinstance(value, dict):
            safe[str(key)] = _safe_metadata(value)
        elif isinstance(value, list):
            safe[str(key)] = [item for item in value if isinstance(item, (str, int, float, bool))]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def content_revision_checksum(
    *,
    title: str,
    body: str,
    summary: str = "",
    language: str = "",
    metadata: dict[str, Any] | None = None,
    primary_source_type: str = "written",
    primary_source_entity_id: str = "",
    primary_source_ref: str = "",
    canonical_text_representation: str = "",
    source_provenance: dict[str, Any] | None = None,
) -> str:
    payload = {
        "contract_version": CONTENT_REVISION_CONTRACT_VERSION,
        "title": title.strip(),
        "body": body.replace("\r\n", "\n").strip(),
        "summary": summary.strip(),
        "language": language.strip().lower(),
        "metadata": _safe_metadata(metadata),
        "primary_source_type": primary_source_type.strip(),
        "primary_source_entity_id": primary_source_entity_id.strip(),
        "primary_source_ref": primary_source_ref.strip(),
        "canonical_text_representation": (canonical_text_representation or body).replace("\r\n", "\n").strip(),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def variant_checksum(variant: ChannelContentVariant) -> str:
    payload = {
        "contract_version": CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION,
        "source_revision_id": variant.source_revision_id,
        "channel_plugin_id": variant.channel_plugin_id,
        "capability": variant.capability,
        "title": variant.title.strip(),
        "body": variant.body.replace("\r\n", "\n").strip(),
        "summary": variant.summary.strip(),
        "hashtags": list(variant.hashtags or []),
        "mentions": list(variant.mentions or []),
        "call_to_action": variant.call_to_action.strip(),
        "language": variant.language.strip().lower(),
        "metadata": _safe_metadata(variant.metadata),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _content_text_from_legacy(item: Any) -> str:
    if getattr(item, "markdown_body", ""):
        return plain_text_from_markdown(getattr(item, "markdown_body", ""))
    return str(getattr(item, "html_body", "") or "")


def _workspace_for_channel_plugin(channel_plugin_id: str) -> str:
    return channel_plugin_id.removeprefix("channel.") if channel_plugin_id.startswith("channel.") else channel_plugin_id


class ContentRepository:
    def create(self, item: ContentItem) -> ContentItem:
        def mutate(records: list[ContentItem]):
            if any(record.id == item.id for record in records):
                raise ContentConflictError("content.item_exists", "Content item already exists.")
            records.append(item)
            return True, item

        return _mutate_records(content_items_path(), ContentItem, mutate)

    def save(self, item: ContentItem) -> ContentItem:
        def mutate(records: list[ContentItem]):
            for index, record in enumerate(records):
                if record.id == item.id:
                    records[index] = item
                    return True, item
            records.append(item)
            return True, item

        return _mutate_records(content_items_path(), ContentItem, mutate)

    def get(self, item_id: str) -> ContentItem | None:
        return next((record for record in self.list() if record.id == item_id), None)

    def list(self, *, workspace_id: str = "", include_deleted: bool = False) -> list[ContentItem]:
        records = _load_records(content_items_path(), ContentItem)
        if workspace_id:
            records = [record for record in records if record.workspace_id == workspace_id]
        if not include_deleted:
            records = [record for record in records if record.status != ContentStatus.DELETED.value]
        return sorted(records, key=lambda item: (item.updated_at or item.created_at, item.id), reverse=True)

    def find_by_source_reference(self, source_type: str, source_reference: str, *, workspace_id: str = ""):
        for record in self.list(workspace_id=workspace_id, include_deleted=True):
            if record.source_type == source_type and record.source_reference == source_reference:
                return record
        return None

    def exists(self, item_id: str, *, workspace_id: str = "") -> bool:
        item = self.get(item_id)
        return item is not None and (not workspace_id or item.workspace_id == workspace_id)


class RevisionRepository:
    def create(self, revision: ContentRevision) -> ContentRevision:
        def mutate(records: list[ContentRevision]):
            if any(record.id == revision.id for record in records):
                raise ContentConflictError("content.revision_exists", "Content revision already exists.")
            records.append(revision)
            return True, revision

        return _mutate_records(content_revisions_path(), ContentRevision, mutate)

    def get(self, revision_id: str) -> ContentRevision | None:
        return next((record for record in self.list_all() if record.id == revision_id), None)

    def list_all(self) -> list[ContentRevision]:
        return _load_records(content_revisions_path(), ContentRevision)

    def list_by_content(self, content_item_id: str) -> list[ContentRevision]:
        records = [record for record in self.list_all() if record.content_item_id == content_item_id]
        return sorted(records, key=lambda item: (item.revision_number, item.created_at, item.id))

    def current(self, item: ContentItem) -> ContentRevision | None:
        if item.current_revision_id:
            return self.get(item.current_revision_id)
        revisions = self.list_by_content(item.id)
        return revisions[-1] if revisions else None

    def next_revision_number(self, content_item_id: str) -> int:
        revisions = self.list_by_content(content_item_id)
        return max((revision.revision_number for revision in revisions), default=0) + 1


class ChannelVariantRepository:
    def create(self, variant: ChannelContentVariant) -> ChannelContentVariant:
        def mutate(records: list[ChannelContentVariant]):
            if any(record.id == variant.id for record in records):
                raise ContentConflictError("content.variant_exists", "Channel content variant already exists.")
            if variant.status == ChannelContentVariantStatus.READY.value:
                self._ensure_no_duplicate_ready(records, variant)
            records.append(variant)
            return True, variant

        return _mutate_records(channel_variants_path(), ChannelContentVariant, mutate)

    def save(self, variant: ChannelContentVariant) -> ChannelContentVariant:
        def mutate(records: list[ChannelContentVariant]):
            if variant.status == ChannelContentVariantStatus.READY.value:
                self._ensure_no_duplicate_ready(records, variant)
            for index, record in enumerate(records):
                if record.id == variant.id:
                    records[index] = variant
                    return True, variant
            records.append(variant)
            return True, variant

        return _mutate_records(channel_variants_path(), ChannelContentVariant, mutate)

    def get(self, variant_id: str) -> ChannelContentVariant | None:
        return next((record for record in self.list_all() if record.id == variant_id), None)

    def list_all(self) -> list[ChannelContentVariant]:
        return _load_records(channel_variants_path(), ChannelContentVariant)

    def list_by_content(self, content_item_id: str, *, include_archived: bool = False):
        records = [record for record in self.list_all() if record.content_item_id == content_item_id]
        if not include_archived:
            records = [record for record in records if record.status != ChannelContentVariantStatus.ARCHIVED.value]
        return sorted(records, key=lambda item: (item.channel_plugin_id, item.capability, item.updated_at, item.id))

    def select_active(
        self, content_item_id: str, channel_plugin_id: str, capability: str, source_revision_id: str = ""
    ):
        candidates = [
            record
            for record in self.list_by_content(content_item_id)
            if record.channel_plugin_id == channel_plugin_id
            and record.capability == capability
            and record.status == ChannelContentVariantStatus.READY.value
            and (not source_revision_id or record.source_revision_id == source_revision_id)
        ]
        return sorted(candidates, key=lambda item: (item.updated_at, item.id), reverse=True)[0] if candidates else None

    def mark_stale_for_revision_change(
        self, content_item_id: str, current_revision_id: str
    ) -> list[ChannelContentVariant]:
        stale: list[ChannelContentVariant] = []

        def mutate(records: list[ChannelContentVariant]):
            changed = False
            for record in records:
                if (
                    record.content_item_id == content_item_id
                    and record.source_revision_id != current_revision_id
                    and record.status == ChannelContentVariantStatus.READY.value
                ):
                    record.status = ChannelContentVariantStatus.STALE.value
                    record.updated_at = channel_store.now_iso()
                    stale.append(record)
                    changed = True
            return changed, stale

        return _mutate_records(channel_variants_path(), ChannelContentVariant, mutate)

    @staticmethod
    def _ensure_no_duplicate_ready(records: list[ChannelContentVariant], variant: ChannelContentVariant) -> None:
        for record in records:
            if record.id == variant.id:
                continue
            if (
                record.workspace_id == variant.workspace_id
                and record.content_item_id == variant.content_item_id
                and record.channel_plugin_id == variant.channel_plugin_id
                and record.capability == variant.capability
                and record.status == ChannelContentVariantStatus.READY.value
            ):
                raise ContentConflictError("content.variant_duplicate_ready", "A ready variant already exists.")


class ContentRequirementRegistry:
    def __init__(self) -> None:
        self._requirements: dict[tuple[str, str], ChannelContentRequirements] = {}

    def register(self, requirements: ChannelContentRequirements) -> ChannelContentRequirements:
        key = (requirements.channel_plugin_id, requirements.capability)
        current = self._requirements.get(key)
        if current is not None and asdict(current) != asdict(requirements):
            raise ContentConflictError("content.requirement_conflict", "Conflicting channel requirements.")
        self._requirements[key] = requirements
        return requirements

    def get(self, channel_plugin_id: str, capability: str) -> ChannelContentRequirements:
        requirement = self._requirements.get((channel_plugin_id, capability))
        if requirement is None:
            raise ContentNotFoundError("content.requirements_not_found", "Content requirements were not found.")
        return requirement

    def list_channel_requirements(self, channel_plugin_id: str = "") -> list[ChannelContentRequirements]:
        records = list(self._requirements.values())
        if channel_plugin_id:
            records = [record for record in records if record.channel_plugin_id == channel_plugin_id]
        return sorted(records, key=lambda item: (item.channel_plugin_id, item.capability))

    def validate(
        self,
        *,
        channel_plugin_id: str,
        capability: str,
        title: str,
        body: str,
        language: str = "",
        hashtags: list[str] | None = None,
        selected_revision_id: str = "",
        selected_variant_id: str = "",
        direct_use: bool = False,
    ) -> ContentRequirementResult:
        requirements = self.get(channel_plugin_id, capability)
        violations: list[ContentRequirementViolation] = []
        warnings: list[ContentRequirementViolation] = []
        normalized_body = body.replace("\r\n", "\n").strip()
        normalized_title = title.strip()
        if requirements.body_required and not normalized_body:
            violations.append(ContentRequirementViolation("body_required", "Body is required.", "body"))
        if requirements.min_body_length and len(normalized_body) < requirements.min_body_length:
            violations.append(ContentRequirementViolation("body_too_short", "Body is shorter than allowed.", "body"))
        if requirements.max_body_length and len(normalized_body) > requirements.max_body_length:
            violations.append(ContentRequirementViolation("body_too_long", "Body is longer than allowed.", "body"))
        if requirements.title_required and not normalized_title:
            violations.append(ContentRequirementViolation("title_required", "Title is required.", "title"))
        if not requirements.title_supported and normalized_title:
            warnings.append(
                ContentRequirementViolation("title_not_used", "Title is not used by this capability.", "title")
            )
        if requirements.max_title_length and len(normalized_title) > requirements.max_title_length:
            violations.append(ContentRequirementViolation("title_too_long", "Title is longer than allowed.", "title"))
        if requirements.supported_languages and language and language not in requirements.supported_languages:
            violations.append(
                ContentRequirementViolation("language_unsupported", "Language is not supported.", "language")
            )
        tag_count = len(hashtags or [])
        if tag_count and not requirements.hashtags_supported:
            violations.append(
                ContentRequirementViolation("hashtags_unsupported", "Hashtags are not supported.", "hashtags")
            )
        if requirements.max_hashtags and tag_count > requirements.max_hashtags:
            violations.append(ContentRequirementViolation("too_many_hashtags", "Too many hashtags.", "hashtags"))
        if requirements.variant_required and direct_use:
            violations.append(
                ContentRequirementViolation("variant_required", "A channel variant is required.", "variant")
            )
        return ContentRequirementResult(
            suitable=not violations,
            direct_use=direct_use and not violations and not requirements.variant_required,
            variant_required=requirements.variant_required,
            violations=tuple(violations),
            warnings=tuple(warnings),
            requirement_version=requirements.version,
            selected_revision_id=selected_revision_id,
            selected_variant_id=selected_variant_id,
        )


class LegacyContentAdapter:
    def __init__(self, service: ContentService) -> None:
        self.service = service

    def load(self, identifier: str, *, workspace_id: str = "content") -> ContentItem | None:
        existing = self.service.content_repository.find_by_source_reference(
            "legacy_content", identifier, workspace_id=workspace_id
        )
        if existing is not None:
            return existing
        legacy = get_content_item(getattr(self.service.config, "content_dir", CONTENT_DRAFTS_DIR), identifier)
        if legacy is None:
            return None
        title = getattr(legacy, "title", "") or "Untitled"
        body = _content_text_from_legacy(legacy)
        return self.service.create_content(
            workspace_id=workspace_id,
            title=title,
            body=body,
            summary=getattr(legacy, "subtitle", ""),
            language="",
            content_type=ContentType.SOCIAL_POST.value,
            created_by="legacy_adapter",
            source_type="legacy_content",
            source_reference=getattr(legacy, "id", identifier),
            primary_source_type="written",
            primary_source_ref=getattr(legacy, "id", identifier),
            canonical_text_representation=body,
            source_provenance={"actor_type": "import", "provider": "legacy_content_adapter"},
            metadata={
                "compatibility_source": "content_store",
                "legacy_slug": getattr(legacy, "slug", ""),
                "legacy_channels": list(getattr(legacy, "channels", []) or []),
            },
            change_reason="lazy_legacy_migration",
        )


class AgenticGraphService:
    def save_entity(self, entity: Entity) -> Entity:
        def mutate(records: list[Entity]):
            for index, record in enumerate(records):
                if record.id == entity.id:
                    records[index] = entity
                    return True, entity
            records.append(entity)
            return True, entity

        return _mutate_records(entities_path(), Entity, mutate)

    def list_entities(self, *, entity_type: str = "") -> list[Entity]:
        records = _load_records(entities_path(), Entity)
        if entity_type:
            records = [record for record in records if record.entity_type == entity_type]
        return sorted(records, key=lambda item: (item.updated_at or item.created_at, item.id), reverse=True)

    def add_relationship(
        self,
        *,
        workspace_id: str,
        from_entity_id: str,
        relationship_type: str,
        to_entity_id: str,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> Relationship:
        now = channel_store.now_iso()
        relationship = Relationship(
            id=f"relationship_{uuid4().hex}",
            workspace_id=workspace_id,
            from_entity_id=from_entity_id,
            relationship_type=relationship_type,
            to_entity_id=to_entity_id,
            metadata=_safe_metadata(metadata),
            provenance=ProvenanceRecord(**_safe_metadata(provenance))
            if provenance
            else ProvenanceRecord(created_at=now),
            created_at=now,
        )

        def mutate(records: list[Relationship]):
            records.append(relationship)
            return True, relationship

        return _mutate_records(relationships_path(), Relationship, mutate)

    def list_relationships(self, *, entity_id: str = "", relationship_type: str = "") -> list[Relationship]:
        records = _load_records(relationships_path(), Relationship)
        if entity_id:
            records = [r for r in records if r.from_entity_id == entity_id or r.to_entity_id == entity_id]
        if relationship_type:
            records = [r for r in records if r.relationship_type == relationship_type]
        return records

    def record_transformation_run(
        self,
        *,
        workspace_id: str,
        transformation: TransformationContract,
        input_refs: tuple[str, ...],
        output_refs: tuple[str, ...] = (),
        configuration: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> TransformationRun:
        run = TransformationRun(
            id=f"transformation_run_{uuid4().hex}",
            workspace_id=workspace_id,
            transformation_id=transformation.id,
            plugin_id=transformation.plugin_id,
            input_refs=input_refs,
            output_refs=output_refs,
            configuration=_safe_metadata(configuration),
            evidence=_safe_metadata(evidence),
            provenance=ProvenanceRecord(
                actor_type="plugin", plugin_id=transformation.plugin_id, created_at=channel_store.now_iso()
            ),
            created_at=channel_store.now_iso(),
        )

        def mutate(records: list[TransformationRun]):
            records.append(run)
            return True, run

        return _mutate_records(transformation_runs_path(), TransformationRun, mutate)

    def list_transformation_runs(self, *, workspace_id: str = "") -> list[TransformationRun]:
        records = _load_records(transformation_runs_path(), TransformationRun)
        return [record for record in records if not workspace_id or record.workspace_id == workspace_id]

    def save_campaign(self, campaign: Campaign) -> Campaign:
        def mutate(records: list[Campaign]):
            for index, record in enumerate(records):
                if record.id == campaign.id:
                    records[index] = campaign
                    return True, campaign
            records.append(campaign)
            return True, campaign

        return _mutate_records(campaigns_path(), Campaign, mutate)

    def list_campaigns(self, *, workspace_id: str = "") -> list[Campaign]:
        records = _load_records(campaigns_path(), Campaign)
        return [record for record in records if not workspace_id or record.workspace_id == workspace_id]

    def save_outcome(self, outcome: Outcome) -> Outcome:
        def mutate(records: list[Outcome]):
            records.append(outcome)
            return True, outcome

        return _mutate_records(outcomes_path(), Outcome, mutate)

    def list_outcomes(self, *, workspace_id: str = "") -> list[Outcome]:
        records = _load_records(outcomes_path(), Outcome)
        return [record for record in records if not workspace_id or record.workspace_id == workspace_id]

    def save_playbook(self, playbook: Playbook) -> Playbook:
        def mutate(records: list[Playbook]):
            for index, record in enumerate(records):
                if record.id == playbook.id:
                    records[index] = playbook
                    return True, playbook
            records.append(playbook)
            return True, playbook

        return _mutate_records(playbooks_path(), Playbook, mutate)

    def list_playbooks(self) -> list[Playbook]:
        return _load_records(playbooks_path(), Playbook)

    def validate_policy(self, policy: PolicyRule) -> tuple[bool, str]:
        if policy.effect not in {"allow", "deny", "require_confirmation"}:
            return False, "policy.effect_invalid"
        if any(str(key).startswith("exec") or str(key).startswith("eval") for key in policy.conditions):
            return False, "policy.executable_condition_forbidden"
        return True, "ok"

    def save_policy(self, policy: PolicyRule) -> PolicyRule:
        ok, code = self.validate_policy(policy)
        if not ok:
            raise ContentValidationError(code, "Policy rule is invalid.")

        def mutate(records: list[PolicyRule]):
            records.append(policy)
            return True, policy

        return _mutate_records(policies_path(), PolicyRule, mutate)

    def agent_context(self, *, workspace_id: str, content_service: ContentService) -> dict[str, Any]:
        items = content_service.list_content(workspace_id=workspace_id, include_deleted=False)
        variants = content_service.variant_repository.list_all()
        revisions = content_service.revision_repository.list_all()
        return {
            "entities": [asdict(entity) for entity in self.list_entities()],
            "content": [asdict(item) for item in items],
            "primary_sources": [
                {
                    "content_item_id": item.id,
                    "primary_source_type": item.primary_source_type or item.source_type or "written",
                    "primary_source_entity_id": item.primary_source_entity_id,
                    "primary_source_ref": item.primary_source_ref or item.source_reference,
                    "canonical_text_representation": item.canonical_text_representation or item.body,
                    "canonical_media_refs": list(item.canonical_media_refs),
                    "canonical_metadata": dict(item.canonical_metadata),
                    "provenance": dict(item.source_provenance),
                }
                for item in items
            ],
            "relationships": [asdict(relationship) for relationship in self.list_relationships()],
            "transformations": [asdict(run) for run in self.list_transformation_runs(workspace_id=workspace_id)],
            "variants": [asdict(variant) for variant in variants if variant.workspace_id == workspace_id],
            "revisions": [asdict(revision) for revision in revisions if revision.workspace_id == workspace_id],
            "campaigns": [asdict(campaign) for campaign in self.list_campaigns(workspace_id=workspace_id)],
            "outcomes": [asdict(outcome) for outcome in self.list_outcomes(workspace_id=workspace_id)],
            "playbooks": [asdict(playbook) for playbook in self.list_playbooks()],
        }


class DeterministicClipCandidateTransformation:
    contract = TransformationContract(
        id="transformation.transcript.clip_candidates.deterministic",
        plugin_id="plugin.transcript_clip_candidates.fixture",
        accepts=("asset.transcript.timeline",),
        produces=("asset.clip_candidate",),
    )

    def run(self, segments: list[TimelineSegment], *, max_candidates: int = 3) -> list[ClipCandidate]:
        candidates: list[ClipCandidate] = []
        for segment in segments:
            duration = max(0.0, float(segment.end_time) - float(segment.start_time))
            text = segment.text.strip()
            if not text or duration <= 0:
                continue
            keyword_bonus = (
                0.25 if any(word in text.lower() for word in ["launch", "why", "how", "secret", "mistake"]) else 0.0
            )
            duration_score = 1.0 - min(abs(duration - 45.0) / 45.0, 1.0)
            score = round(0.55 * duration_score + 0.35 * min(len(text) / 240.0, 1.0) + keyword_bonus, 4)
            candidates.append(
                ClipCandidate(
                    start=float(segment.start_time),
                    end=float(segment.end_time),
                    transcript_excerpt=text[:280],
                    score=score,
                    reason="duration_text_keyword_score",
                    provenance=ProvenanceRecord(actor_type="plugin", plugin_id=self.contract.plugin_id),
                )
            )
        return sorted(candidates, key=lambda item: (-item.score, item.start))[:max_candidates]

    def render_synthetic_short_asset(
        self, candidate: ClipCandidate, *, synthetic_video_ref: str = ""
    ) -> dict[str, Any]:
        if not synthetic_video_ref:
            return {"status": "unsupported", "reason": "synthetic_video_missing"}
        return {
            "status": "available",
            "asset_type": "short_clip",
            "source_ref": synthetic_video_ref,
            "start": candidate.start,
            "end": candidate.end,
            "provenance": {"plugin_id": self.contract.plugin_id, "transformation_id": self.contract.id},
        }


class ContentService:
    def __init__(self, *, app_runtime, config) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.content_repository = ContentRepository()
        self.revision_repository = RevisionRepository()
        self.variant_repository = ChannelVariantRepository()
        self.requirement_registry = ContentRequirementRegistry()
        self.graph_service = AgenticGraphService()
        self.media_library_service = app_runtime.media_library_service(config)
        self.legacy_adapter = LegacyContentAdapter(self)

    def create_content(
        self,
        *,
        workspace_id: str,
        title: str,
        body: str,
        summary: str = "",
        language: str = "",
        content_type: str = ContentType.SOCIAL_POST.value,
        created_by: str = "",
        source_type: str = "",
        source_reference: str = "",
        primary_source_type: str = "",
        primary_source_entity_id: str = "",
        primary_source_ref: str = "",
        primary_source_metadata: dict[str, Any] | None = None,
        canonical_text_representation: str = "",
        canonical_media_refs: list[str] | None = None,
        canonical_metadata: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        change_reason: str = "create",
    ) -> ContentItem:
        now = channel_store.now_iso()
        resolved_primary_source_type = (primary_source_type or source_type or "written").strip()
        resolved_primary_source_ref = (primary_source_ref or source_reference or "").strip()
        resolved_canonical_text = (canonical_text_representation or body).replace("\r\n", "\n").strip()
        resolved_source_provenance = dict(source_provenance or {})
        if not resolved_source_provenance:
            resolved_source_provenance = {"actor_type": "manual", "provider": "content_service", "created_at": now}
        item = ContentItem(
            id=f"content_{uuid4().hex}",
            workspace_id=workspace_id,
            content_type=content_type
            if content_type in {item.value for item in ContentType}
            else ContentType.UNKNOWN.value,
            title=title.strip() or "Untitled",
            body=body.replace("\r\n", "\n").strip(),
            summary=summary.strip(),
            language=language.strip().lower(),
            status=ContentStatus.DRAFT.value,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            source_type=source_type or resolved_primary_source_type,
            source_reference=source_reference or resolved_primary_source_ref,
            primary_source_type=resolved_primary_source_type,
            primary_source_entity_id=primary_source_entity_id.strip(),
            primary_source_ref=resolved_primary_source_ref,
            primary_source_metadata=_safe_metadata(primary_source_metadata),
            canonical_text_representation=resolved_canonical_text,
            canonical_media_refs=list(canonical_media_refs or []),
            canonical_metadata=_safe_metadata(canonical_metadata),
            source_provenance=_safe_metadata(resolved_source_provenance),
            metadata=_safe_metadata(metadata),
        )
        self.content_repository.create(item)
        revision = self._create_revision(item, actor=created_by, change_reason=change_reason)
        item.current_revision_id = revision.id
        item.status = self._derive_content_status(item)
        item.updated_at = channel_store.now_iso()
        self.content_repository.save(item)
        self._event("content.item.created", item.workspace_id, "content_item", item.id, created_by)
        self._audit("content.create", item.workspace_id, "content_item", item.id, created_by)
        return item

    def create_written_content(
        self,
        *,
        workspace_id: str,
        title: str,
        body: str,
        summary: str = "",
        language: str = "",
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ContentItem:
        return self.create_content(
            workspace_id=workspace_id,
            title=title,
            body=body,
            summary=summary,
            language=language,
            content_type=ContentType.SOCIAL_POST.value,
            created_by=created_by,
            primary_source_type="written",
            canonical_text_representation=body,
            source_provenance={"actor_type": "manual", "provider": "content_service"},
            metadata=metadata,
            change_reason="create_written_source",
        )

    def create_youtube_source_content(
        self,
        *,
        workspace_id: str,
        youtube_url: str,
        video_id: str,
        title: str,
        transcript: str,
        transcript_provenance: dict[str, Any] | None = None,
        edited_transcript: str = "",
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ContentItem:
        canonical_transcript = (edited_transcript or transcript).replace("\r\n", "\n").strip()
        provenance = {
            "actor_type": "manual",
            "provider": "transcript_import",
            "original_ref": youtube_url.strip(),
            "original_transcript_preserved": bool(transcript.strip()),
        }
        provenance.update(transcript_provenance or {})
        canonical_metadata = {
            "video_id": video_id.strip(),
            "transcript_original": transcript,
            "transcript_edited": edited_transcript,
            "transcript_changed": bool(edited_transcript and edited_transcript != transcript),
        }
        return self.create_content(
            workspace_id=workspace_id,
            title=title,
            body=canonical_transcript,
            summary="",
            language="",
            content_type=ContentType.SOCIAL_POST.value,
            created_by=created_by,
            source_type="youtube_video",
            source_reference=video_id.strip() or youtube_url.strip(),
            primary_source_type="youtube_video",
            primary_source_ref=youtube_url.strip(),
            primary_source_metadata={"video_id": video_id.strip(), "url": youtube_url.strip()},
            canonical_text_representation=canonical_transcript,
            canonical_metadata=canonical_metadata,
            source_provenance=provenance,
            metadata=metadata,
            change_reason="create_youtube_source",
        )

    def update_content(
        self,
        content_item_id: str,
        *,
        workspace_id: str,
        title: str | None = None,
        body: str | None = None,
        summary: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "",
        expected_revision_id: str = "",
        change_reason: str = "update",
    ) -> ContentItem:
        item = self.get_content(content_item_id, workspace_id=workspace_id)
        if expected_revision_id and item.current_revision_id != expected_revision_id:
            raise ContentConflictError("content.revision_conflict", "Current revision changed.")
        item.title = item.title if title is None else title.strip()
        item.body = item.body if body is None else body.replace("\r\n", "\n").strip()
        item.summary = item.summary if summary is None else summary.strip()
        item.language = item.language if language is None else language.strip().lower()
        if metadata is not None:
            item.metadata = _safe_metadata(metadata)
        item.updated_at = channel_store.now_iso()
        item.updated_by = actor
        revision = self._create_revision(item, actor=actor, change_reason=change_reason)
        item.current_revision_id = revision.id
        item.status = self._derive_content_status(item)
        self.content_repository.save(item)
        for variant in self.variant_repository.mark_stale_for_revision_change(item.id, item.current_revision_id):
            self._event("content.variant.stale", item.workspace_id, "channel_variant", variant.id, actor)
        self._event("content.revision.created", item.workspace_id, "content_revision", revision.id, actor)
        self._audit("revision.create", item.workspace_id, "content_item", item.id, actor)
        return item

    def get_content(self, content_item_id: str, *, workspace_id: str = "", allow_legacy: bool = True) -> ContentItem:
        item = self.content_repository.get(content_item_id)
        if item is None and allow_legacy:
            item = self.legacy_adapter.load(content_item_id, workspace_id=workspace_id or "content")
        if item is None or (workspace_id and item.workspace_id != workspace_id):
            raise ContentNotFoundError("content.item_not_found", "Content item was not found.")
        return item

    def list_content(self, *, workspace_id: str = "", include_deleted: bool = False) -> list[ContentItem]:
        return self.content_repository.list(workspace_id=workspace_id, include_deleted=include_deleted)

    def archive_content(self, content_item_id: str, *, workspace_id: str, actor: str = "") -> ContentItem:
        item = self.get_content(content_item_id, workspace_id=workspace_id)
        item.status = ContentStatus.ARCHIVED.value
        item.updated_at = channel_store.now_iso()
        item.updated_by = actor
        self.content_repository.save(item)
        self._event("content.item.archived", item.workspace_id, "content_item", item.id, actor)
        self._audit("content.archive", item.workspace_id, "content_item", item.id, actor)
        return item

    def restore_revision(
        self, content_item_id: str, revision_id: str, *, workspace_id: str, actor: str = "", reason: str = "restore"
    ) -> ContentItem:
        item = self.get_content(content_item_id, workspace_id=workspace_id)
        revision = self.revision_repository.get(revision_id)
        if revision is None or revision.content_item_id != item.id:
            raise ContentNotFoundError("content.revision_not_found", "Content revision was not found.")
        item.title = revision.title
        item.body = revision.body
        item.summary = revision.summary
        item.language = revision.language
        item.metadata = dict(revision.metadata)
        restored = self.update_content(
            item.id,
            workspace_id=workspace_id,
            title=item.title,
            body=item.body,
            summary=item.summary,
            language=item.language,
            metadata=item.metadata,
            actor=actor,
            change_reason=reason,
        )
        self._audit("revision.restore", workspace_id, "content_revision", revision_id, actor, reason=reason)
        return restored

    def create_variant(
        self,
        *,
        workspace_id: str,
        content_item_id: str,
        source_revision_id: str = "",
        channel_plugin_id: str,
        capability: str,
        title: str = "",
        body: str = "",
        summary: str = "",
        hashtags: list[str] | None = None,
        mentions: list[dict[str, Any]] | None = None,
        call_to_action: str = "",
        language: str = "",
        variant_type: str = ChannelContentVariantType.MANUAL.value,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ChannelContentVariant:
        item = self.get_content(content_item_id, workspace_id=workspace_id)
        revision = self.revision_repository.get(source_revision_id or item.current_revision_id)
        if revision is None or revision.content_item_id != item.id:
            raise ContentNotFoundError("content.revision_not_found", "Content revision was not found.")
        variant = ChannelContentVariant(
            id=f"content_variant_{uuid4().hex}",
            workspace_id=workspace_id,
            content_item_id=item.id,
            source_revision_id=revision.id,
            channel_plugin_id=channel_plugin_id,
            capability=capability,
            variant_type=variant_type
            if variant_type in {variant.value for variant in ChannelContentVariantType}
            else ChannelContentVariantType.MANUAL.value,
            title=title,
            body=body.replace("\r\n", "\n").strip(),
            summary=summary,
            hashtags=list(hashtags or []),
            mentions=list(mentions or []),
            call_to_action=call_to_action,
            language=language or revision.language,
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
            created_by=created_by,
            updated_by=created_by,
            metadata=_safe_metadata(metadata),
            primary_source_type=revision.primary_source_type
            or item.primary_source_type
            or item.source_type
            or "written",
            primary_source_entity_id=revision.primary_source_entity_id or item.primary_source_entity_id,
            primary_source_ref=revision.primary_source_ref or item.primary_source_ref or item.source_reference,
            campaign_id=str((metadata or {}).get("campaign_id") or item.metadata.get("campaign_id") or ""),
            intent_id=str((metadata or {}).get("intent_id") or item.metadata.get("intent_id") or ""),
            transformation_run_id=str((metadata or {}).get("transformation_run_id") or ""),
            source_provenance=dict(revision.source_provenance or item.source_provenance),
        )
        result = self.requirement_registry.validate(
            channel_plugin_id=channel_plugin_id,
            capability=capability,
            title=variant.title,
            body=variant.body,
            language=variant.language,
            hashtags=variant.hashtags,
            selected_revision_id=revision.id,
            selected_variant_id=variant.id,
        )
        variant.requirement_version = result.requirement_version
        variant.validation_status = "valid" if result.suitable else "invalid"
        variant.status = (
            ChannelContentVariantStatus.READY.value if result.suitable else ChannelContentVariantStatus.INVALID.value
        )
        variant.variant_checksum = variant_checksum(variant)
        saved = self.variant_repository.create(variant)
        self._event("content.variant.created", workspace_id, "channel_variant", saved.id, created_by)
        self._audit("variant.create", workspace_id, "channel_variant", saved.id, created_by)
        return saved

    def update_variant(
        self, variant_id: str, *, workspace_id: str, actor: str = "", **updates
    ) -> ChannelContentVariant:
        variant = self.variant_repository.get(variant_id)
        if variant is None or variant.workspace_id != workspace_id:
            raise ContentNotFoundError("content.variant_not_found", "Channel variant was not found.")
        for field_name in ("title", "body", "summary", "call_to_action", "language"):
            if field_name in updates:
                setattr(variant, field_name, str(updates[field_name] or "").replace("\r\n", "\n").strip())
        if "hashtags" in updates and isinstance(updates["hashtags"], list):
            variant.hashtags = [str(item) for item in updates["hashtags"]]
        if "mentions" in updates and isinstance(updates["mentions"], list):
            variant.mentions = [item for item in updates["mentions"] if isinstance(item, dict)]
        if "metadata" in updates:
            variant.metadata = _safe_metadata(updates.get("metadata"))
        result = self.validate_variant(variant.id, workspace_id=workspace_id, persist=False)
        variant.validation_status = "valid" if result.suitable else "invalid"
        variant.status = (
            ChannelContentVariantStatus.READY.value if result.suitable else ChannelContentVariantStatus.INVALID.value
        )
        variant.requirement_version = result.requirement_version
        variant.variant_checksum = variant_checksum(variant)
        variant.updated_at = channel_store.now_iso()
        variant.updated_by = actor
        saved = self.variant_repository.save(variant)
        self._event("content.variant.updated", workspace_id, "channel_variant", saved.id, actor)
        self._audit("variant.update", workspace_id, "channel_variant", saved.id, actor)
        return saved

    def validate_variant(self, variant_id: str, *, workspace_id: str, persist: bool = True) -> ContentRequirementResult:
        variant = self.variant_repository.get(variant_id)
        if variant is None or variant.workspace_id != workspace_id:
            raise ContentNotFoundError("content.variant_not_found", "Channel variant was not found.")
        result = self.requirement_registry.validate(
            channel_plugin_id=variant.channel_plugin_id,
            capability=variant.capability,
            title=variant.title,
            body=variant.body,
            language=variant.language,
            hashtags=variant.hashtags,
            selected_revision_id=variant.source_revision_id,
            selected_variant_id=variant.id,
        )
        if persist:
            variant.validation_status = "valid" if result.suitable else "invalid"
            variant.status = (
                ChannelContentVariantStatus.READY.value
                if result.suitable
                else ChannelContentVariantStatus.INVALID.value
            )
            variant.requirement_version = result.requirement_version
            variant.variant_checksum = variant_checksum(variant)
            variant.updated_at = channel_store.now_iso()
            self.variant_repository.save(variant)
        return result

    def resolve_channel_content(
        self,
        *,
        content_item_id: str,
        workspace_id: str,
        channel_plugin_id: str,
        capability: str,
        source_revision_id: str = "",
        channel_variant_id: str = "",
    ) -> tuple[ContentRevision, ChannelContentVariant | None, ContentRequirementResult]:
        item = self.get_content(content_item_id, workspace_id=workspace_id)
        revision = self.revision_repository.get(source_revision_id or item.current_revision_id)
        if revision is None or revision.content_item_id != item.id:
            raise ContentNotFoundError("content.revision_not_found", "Content revision was not found.")
        explicit_variant = self.variant_repository.get(channel_variant_id) if channel_variant_id else None
        if explicit_variant is not None:
            if explicit_variant.content_item_id != item.id or explicit_variant.channel_plugin_id != channel_plugin_id:
                raise ContentValidationError("content.variant_mismatch", "Variant does not belong to this target.")
            result = self.requirement_registry.validate(
                channel_plugin_id=channel_plugin_id,
                capability=capability,
                title=explicit_variant.title,
                body=explicit_variant.body,
                language=explicit_variant.language,
                hashtags=explicit_variant.hashtags,
                selected_revision_id=revision.id,
                selected_variant_id=explicit_variant.id,
            )
            return revision, explicit_variant, result
        ready = self.variant_repository.select_active(item.id, channel_plugin_id, capability, revision.id)
        if ready is not None:
            result = self.requirement_registry.validate(
                channel_plugin_id=channel_plugin_id,
                capability=capability,
                title=ready.title,
                body=ready.body,
                language=ready.language,
                hashtags=ready.hashtags,
                selected_revision_id=revision.id,
                selected_variant_id=ready.id,
            )
            return revision, ready, result
        result = self.requirement_registry.validate(
            channel_plugin_id=channel_plugin_id,
            capability=capability,
            title=revision.title,
            body=revision.body,
            language=revision.language,
            selected_revision_id=revision.id,
            direct_use=True,
        )
        return revision, None, result

    def list_variants(self, content_item_id: str, *, workspace_id: str) -> list[ChannelContentVariant]:
        self.get_content(content_item_id, workspace_id=workspace_id)
        return self.variant_repository.list_by_content(content_item_id)

    def scan_integrity(self, *, workspace_id: str = "") -> list[ContentIntegrityIssue]:
        issues: list[ContentIntegrityIssue] = []
        items = self.content_repository.list(workspace_id=workspace_id, include_deleted=True)
        revisions = self.revision_repository.list_all()
        variants = self.variant_repository.list_all()
        revision_ids = {revision.id for revision in revisions}
        item_ids = {item.id for item in items}
        missing_revision = [item for item in items if not item.current_revision_id]
        if missing_revision:
            issues.append(
                ContentIntegrityIssue(
                    "content.item_missing_revision",
                    "Content item has no current revision.",
                    len(missing_revision),
                    tuple({"content_item_id": item.id} for item in missing_revision[:5]),
                )
            )
        missing_current = [
            item for item in items if item.current_revision_id and item.current_revision_id not in revision_ids
        ]
        if missing_current:
            issues.append(
                ContentIntegrityIssue(
                    "content.current_revision_missing",
                    "Current revision is missing.",
                    len(missing_current),
                    tuple(
                        {"content_item_id": item.id, "revision_id": item.current_revision_id}
                        for item in missing_current[:5]
                    ),
                )
            )
        orphan_variants = [variant for variant in variants if variant.content_item_id not in item_ids]
        if orphan_variants:
            issues.append(
                ContentIntegrityIssue(
                    "content.variant_without_item",
                    "Variant points to missing content item.",
                    len(orphan_variants),
                    tuple({"variant_id": variant.id} for variant in orphan_variants[:5]),
                )
            )
        missing_source = [variant for variant in variants if variant.source_revision_id not in revision_ids]
        if missing_source:
            issues.append(
                ContentIntegrityIssue(
                    "content.variant_missing_source_revision",
                    "Variant source revision is missing.",
                    len(missing_source),
                    tuple({"variant_id": variant.id} for variant in missing_source[:5]),
                )
            )
        with _dict_store(content_integrity_path()) as store:
            store.write({"checked_at": channel_store.now_iso(), "issues": [asdict(issue) for issue in issues]})
        for issue in issues:
            self._event("content.integrity.issue_detected", workspace_id, "integrity", issue.code, "")
        return issues

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "content_framework_version": CONTENT_FRAMEWORK_VERSION,
            "item_contract_version": CONTENT_ITEM_CONTRACT_VERSION,
            "revision_contract_version": CONTENT_REVISION_CONTRACT_VERSION,
            "variant_contract_version": CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION,
            "requirements_contract_version": CONTENT_REQUIREMENTS_CONTRACT_VERSION,
            "repositories": {
                "content": True,
                "revisions": True,
                "variants": True,
            },
            "requirements_registered": len(self.requirement_registry.list_channel_requirements()),
            "agentic_graph": True,
            "media_library": bool(self.media_library_service),
        }

    def _create_revision(self, item: ContentItem, *, actor: str, change_reason: str) -> ContentRevision:
        revision = ContentRevision(
            id=f"content_revision_{uuid4().hex}",
            content_item_id=item.id,
            workspace_id=item.workspace_id,
            revision_number=self.revision_repository.next_revision_number(item.id),
            title=item.title,
            body=item.body,
            summary=item.summary,
            language=item.language,
            metadata=dict(item.metadata),
            primary_source_type=item.primary_source_type or item.source_type or "written",
            primary_source_entity_id=item.primary_source_entity_id,
            primary_source_ref=item.primary_source_ref or item.source_reference,
            canonical_representation_id=f"canonical_{item.id}_{item.current_revision_id or 'initial'}",
            canonical_text_representation=item.canonical_text_representation or item.body,
            source_provenance=dict(item.source_provenance),
            relationship_ids=list(item.metadata.get("relationship_ids", []) or []),
            checksum=content_revision_checksum(
                title=item.title,
                body=item.body,
                summary=item.summary,
                language=item.language,
                metadata=item.metadata,
                primary_source_type=item.primary_source_type or item.source_type or "written",
                primary_source_entity_id=item.primary_source_entity_id,
                primary_source_ref=item.primary_source_ref or item.source_reference,
                canonical_text_representation=item.canonical_text_representation or item.body,
                source_provenance=item.source_provenance,
            ),
            created_at=channel_store.now_iso(),
            created_by=actor,
            change_reason=change_reason,
        )
        return self.revision_repository.create(revision)

    def _derive_content_status(self, item: ContentItem) -> str:
        if item.status in {ContentStatus.ARCHIVED.value, ContentStatus.DELETED.value}:
            return item.status
        if item.body.strip():
            return ContentStatus.READY.value
        return ContentStatus.DRAFT.value

    def _event(self, action: str, workspace_id: str, target_type: str, target_id: str, actor: str) -> None:
        with _list_store(content_events_path()) as store:
            records = store.read()
            records.append(
                {
                    "id": f"content_event_{uuid4().hex}",
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
        result: str = "ok",
        safe_error_code: str = "",
        snapshot_checksum: str = "",
    ) -> None:
        audit = ContentAuditEvent(
            id=f"content_audit_{uuid4().hex}",
            workspace_id=workspace_id,
            action=action,
            target_id=target_id,
            target_type=target_type,
            actor=actor,
            reason=reason,
            result=result,
            safe_error_code=safe_error_code,
            snapshot_checksum=snapshot_checksum,
            created_at=channel_store.now_iso(),
        )
        with _list_store(content_audit_path()) as store:
            records = store.read()
            records.append(asdict(audit))
            store.write(records)
