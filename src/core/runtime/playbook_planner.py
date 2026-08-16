from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import PlaybookValidationError
from .playbook_registry import (
    PlaybookDefinitionRecord,
    PlaybookRegistry,
    PlaybookRegistryStatus,
    PlaybookSelectionPolicy,
    PlaybookSelectionResult,
    _contains_registry_secret,
    _context_has_metrics,
    _context_transcript_available,
    _version_key,
)
from .events import utc_now_iso

PLAYBOOK_PLAN_SCHEMA_VERSION = "playbook-plan.v1"
PLAYBOOK_PLANNER_VERSION = "playbook-planner.v1"


@dataclass(frozen=True)
class StepPlan:
    step_id: str
    name: str
    kind: str
    required_inputs: dict[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = field(default_factory=tuple)
    allowed_side_effects: bool = False
    raw_access_required: bool = False
    mutation_required: bool = False
    status: str = "planned"
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class PlaybookPlan:
    plan_id: str
    playbook_id: str
    playbook_version: str
    selection_result: dict[str, Any]
    context_ref: dict[str, Any]
    context_schema_version: str
    step_plans: tuple[StepPlan, ...]
    required_capabilities: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    raw_access_required: bool
    mutation_required: bool
    executable: bool
    dry_run: bool
    executed: bool
    provenance: dict[str, Any]
    generated_at: str
    schema_version: str = PLAYBOOK_PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class PlaybookPlanner:
    def __init__(self, *, registry: PlaybookRegistry, clock=utc_now_iso):
        self.registry = registry
        self.clock = clock

    def plan_for_context(
        self,
        context: dict[str, Any],
        *,
        intent: str | None = None,
        policy: PlaybookSelectionPolicy | None = None,
    ) -> PlaybookPlan:
        selection = self.registry.select_for_context(context, intent=intent, policy=policy)
        definition = selection.first
        if definition is None:
            return self._blocked_plan(
                context=context,
                playbook_id="",
                playbook_version="",
                selection_result=selection,
                blocked_reasons=tuple(_selection_blockers(selection) or ["playbook_not_selected"]),
                policy=policy,
            )
        return self._build_plan(context=context, definition=definition, selection_result=selection, policy=policy)

    def plan_explicit(
        self,
        context: dict[str, Any],
        *,
        playbook_id: str,
        version: str | None = None,
        policy: PlaybookSelectionPolicy | None = None,
    ) -> PlaybookPlan:
        selection_policy = policy or PlaybookSelectionPolicy(available_capabilities=frozenset(self.registry.available_capabilities))
        definition: PlaybookDefinitionRecord | None = None
        if version:
            definition = self.registry.get(playbook_id, version)
        else:
            candidates = [item for item in self.registry.list() if item.playbook_id == playbook_id]
            candidates = sorted(candidates, key=lambda item: (_version_key(item.version), item.version), reverse=True)
            definition = candidates[0] if candidates else None
        if definition is None:
            return self._blocked_plan(
                context=context,
                playbook_id=playbook_id,
                playbook_version=version or "",
                selection_result=PlaybookSelectionResult(
                    selected=(),
                    rejected=(),
                    selected_by={"mode": "explicit", "context_schema_version": str(context.get("schema_version") or "")},
                ),
                blocked_reasons=("playbook_not_found",),
                policy=selection_policy,
            )
        reason = self.registry._selection_rejection_reason(definition, context, intent=None, policy=selection_policy)
        selection = PlaybookSelectionResult(
            selected=(definition,) if not reason else (),
            rejected=()
            if not reason
            else ({"playbook_id": definition.playbook_id, "version": definition.version, "reason": reason},),
            selected_by={
                "mode": "explicit",
                "version_resolution": "exact" if version else "highest_version",
                "context_schema_version": str(context.get("schema_version") or ""),
            },
        )
        return self._build_plan(
            context=context,
            definition=definition,
            selection_result=selection,
            policy=selection_policy,
            explicit_blockers=(reason,) if reason else (),
        )

    def explain_blockers(self, plan: PlaybookPlan) -> tuple[str, ...]:
        return plan.blocked_reasons

    def _build_plan(
        self,
        *,
        context: dict[str, Any],
        definition: PlaybookDefinitionRecord,
        selection_result: PlaybookSelectionResult,
        policy: PlaybookSelectionPolicy | None,
        explicit_blockers: tuple[str, ...] = (),
    ) -> PlaybookPlan:
        blocked = list(explicit_blockers)
        blocked.extend(_context_blockers(definition, context))
        blocked.extend(_capability_blockers(definition, policy or PlaybookSelectionPolicy()))
        blocked.extend(_policy_blockers(definition, policy or PlaybookSelectionPolicy()))
        blocked = sorted(set(item for item in blocked if item))
        step_plans = tuple(_step_plan(step, definition, blocked) for step in _definition_steps(definition))
        required_capabilities = tuple(
            sorted(
                set(definition.capability_requirements.read)
                | set(definition.capability_requirements.optional)
                | set(definition.capability_requirements.mutations)
            )
        )
        generated_at = self.clock()
        plan = PlaybookPlan(
            plan_id=_plan_id(definition.playbook_id, definition.version, context, generated_at),
            playbook_id=definition.playbook_id,
            playbook_version=definition.version,
            selection_result=_selection_summary(selection_result),
            context_ref=_context_ref(context),
            context_schema_version=str(context.get("schema_version") or ""),
            step_plans=step_plans,
            required_capabilities=required_capabilities,
            blocked_reasons=tuple(blocked),
            raw_access_required=bool(
                definition.raw_access_policy.raw_metrics
                or definition.raw_access_policy.raw_transcript
                or definition.raw_access_policy.provider_payloads
                or definition.context_contract.raw_metrics_required
                or definition.context_contract.raw_transcript_required
            ),
            mutation_required=bool(definition.capability_requirements.mutations),
            executable=not blocked,
            dry_run=True,
            executed=False,
            provenance={
                "planner_version": PLAYBOOK_PLANNER_VERSION,
                "playbook_definition_source": definition.provenance.get("definition_source", ""),
                "playbook_definition_version": definition.version,
                "selection_policy": _policy_summary(policy),
                "context_schema_version": str(context.get("schema_version") or ""),
                "context_ref": _context_ref(context),
                "validation_results": {"blocked_reasons": blocked},
            },
            generated_at=generated_at,
        )
        _assert_plan_safe(plan)
        return plan

    def _blocked_plan(
        self,
        *,
        context: dict[str, Any],
        playbook_id: str,
        playbook_version: str,
        selection_result: PlaybookSelectionResult,
        blocked_reasons: tuple[str, ...],
        policy: PlaybookSelectionPolicy | None,
    ) -> PlaybookPlan:
        generated_at = self.clock()
        plan = PlaybookPlan(
            plan_id=_plan_id(playbook_id, playbook_version, context, generated_at),
            playbook_id=playbook_id,
            playbook_version=playbook_version,
            selection_result=_selection_summary(selection_result),
            context_ref=_context_ref(context),
            context_schema_version=str(context.get("schema_version") or ""),
            step_plans=(),
            required_capabilities=(),
            blocked_reasons=tuple(sorted(set(blocked_reasons))),
            raw_access_required=False,
            mutation_required=False,
            executable=False,
            dry_run=True,
            executed=False,
            provenance={
                "planner_version": PLAYBOOK_PLANNER_VERSION,
                "selection_policy": _policy_summary(policy),
                "context_schema_version": str(context.get("schema_version") or ""),
                "context_ref": _context_ref(context),
                "validation_results": {"blocked_reasons": sorted(set(blocked_reasons))},
            },
            generated_at=generated_at,
        )
        _assert_plan_safe(plan)
        return plan


def _context_blockers(definition: PlaybookDefinitionRecord, context: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    contract = definition.context_contract
    if contract.schema_version != str(context.get("schema_version") or ""):
        blockers.append("context_schema_mismatch")
    if contract.requires_transcript and not _context_transcript_available(context):
        blockers.append("transcript_required")
    if contract.requires_publications and not context.get("publications"):
        blockers.append("publication_required")
    if contract.requires_metrics_history and not _context_has_metrics(context):
        blockers.append("metrics_required")
    return blockers


def _capability_blockers(definition: PlaybookDefinitionRecord, policy: PlaybookSelectionPolicy) -> list[str]:
    missing = sorted(set(definition.capability_requirements.read) - set(policy.available_capabilities))
    return ["capability_not_available"] if missing else []


def _policy_blockers(definition: PlaybookDefinitionRecord, policy: PlaybookSelectionPolicy) -> list[str]:
    blockers: list[str] = []
    if definition.status in {PlaybookRegistryStatus.DISABLED.value, PlaybookRegistryStatus.INVALID.value}:
        blockers.append(definition.status)
    if definition.status == PlaybookRegistryStatus.DEPRECATED.value and not policy.allow_deprecated:
        blockers.append("deprecated")
    if definition.capability_requirements.mutations and not policy.allow_mutations:
        blockers.append("mutation_not_allowed")
    if (definition.raw_access_policy.raw_metrics or definition.raw_access_policy.provider_payloads) and not policy.allow_raw_metrics:
        blockers.append("raw_access_not_allowed")
    if definition.raw_access_policy.raw_transcript and not policy.allow_raw_transcript:
        blockers.append("raw_access_not_allowed")
    if definition.raw_access_policy.secrets:
        blockers.append("secrets_not_allowed")
    return blockers


def _definition_steps(definition: PlaybookDefinitionRecord) -> tuple[dict[str, Any], ...]:
    if definition.steps:
        return definition.steps
    return ({"step_id": "read-context", "name": "Read context", "kind": "read"},)


def _step_plan(step: dict[str, Any], definition: PlaybookDefinitionRecord, blockers: list[str]) -> StepPlan:
    step_capabilities = tuple(
        sorted(str(item) for item in step.get("required_capabilities", ()) if str(item))
    ) or definition.capability_requirements.read
    raw_required = bool(
        step.get("raw_access_required", False)
        or definition.raw_access_policy.raw_metrics
        or definition.raw_access_policy.raw_transcript
        or definition.raw_access_policy.provider_payloads
    )
    mutation_required = bool(step.get("mutation_required", False) or definition.capability_requirements.mutations)
    status = "blocked" if blockers else "planned"
    return StepPlan(
        step_id=str(step.get("step_id") or step.get("id") or "step"),
        name=str(step.get("name") or step.get("step_id") or "Step"),
        kind=str(step.get("kind") or "read"),
        required_inputs=dict(step.get("required_inputs") or {}),
        required_capabilities=step_capabilities,
        allowed_side_effects=False,
        raw_access_required=raw_required,
        mutation_required=mutation_required,
        status=status,
        blocked_reasons=tuple(blockers),
        provenance={"playbook_id": definition.playbook_id, "playbook_version": definition.version},
    )


def _selection_blockers(selection: PlaybookSelectionResult) -> tuple[str, ...]:
    return tuple(sorted({str(item.get("reason") or "") for item in selection.rejected if item.get("reason")}))


def _selection_summary(selection: PlaybookSelectionResult) -> dict[str, Any]:
    return {
        "selected": [
            {"playbook_id": item.playbook_id, "version": item.version, "status": item.status}
            for item in selection.selected
        ],
        "rejected": [dict(item) for item in selection.rejected],
        "selected_by": dict(selection.selected_by),
    }


def _policy_summary(policy: PlaybookSelectionPolicy | None) -> dict[str, Any]:
    selected = policy or PlaybookSelectionPolicy()
    return {
        "allow_deprecated": selected.allow_deprecated,
        "allow_mutations": selected.allow_mutations,
        "allow_raw_metrics": selected.allow_raw_metrics,
        "allow_raw_transcript": selected.allow_raw_transcript,
        "select_highest_version": selected.select_highest_version,
        "available_capabilities": sorted(selected.available_capabilities),
    }


def _context_ref(context: dict[str, Any]) -> dict[str, Any]:
    entity = context.get("content_entity") or {}
    revision = context.get("current_revision") or {}
    return {
        "content_entity_id": str(entity.get("content_entity_id") or context.get("content_entity_id") or ""),
        "content_revision_id": str(revision.get("content_revision_id") or ""),
        "schema_version": str(context.get("schema_version") or ""),
    }


def _plan_id(playbook_id: str, version: str, context: dict[str, Any], generated_at: str) -> str:
    payload = {
        "context_ref": _context_ref(context),
        "generated_at": generated_at,
        "playbook_id": playbook_id,
        "version": version,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"playbook_plan_{digest[:32]}"


def _assert_plan_safe(plan: PlaybookPlan) -> None:
    payload = plan.to_dict()
    if _contains_registry_secret(payload):
        raise PlaybookValidationError("playbook_plan.secret_value", "Playbook plan must not contain secrets.")
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "Authorization", "Bearer ", "SECRET_CANARY")
    if any(item in rendered for item in forbidden):
        raise PlaybookValidationError("playbook_plan.raw_or_secret_value", "Playbook plan contains forbidden raw data.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
