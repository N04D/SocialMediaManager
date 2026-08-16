from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .playbook_planner import PlaybookPlan, StepPlan
from .playbook_registry import PlaybookSelectionPolicy, _contains_registry_secret

SANDBOX_EXECUTION_SCHEMA_VERSION = "sandbox-execution.v1"
READ_ONLY_SANDBOX_VERSION = "read-only-playbook-sandbox.v1"

SUPPORTED_SANDBOX_STEP_KINDS = {
    "check_metrics_available",
    "check_transcript_available",
    "inspect_context",
    "list_metric_history",
    "list_publications",
    "summarize_available_fields",
}


@dataclass(frozen=True)
class SandboxRedactionState:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    mutations_used: bool = False


@dataclass(frozen=True)
class StepExecutionResult:
    step_id: str
    status: str
    output_ref_or_value: dict[str, Any] = field(default_factory=dict)
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)
    capability_used: tuple[str, ...] = field(default_factory=tuple)
    raw_access_used: bool = False
    mutation_used: bool = False
    side_effects: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class SandboxExecutionRecord:
    execution_id: str
    plan_id: str
    playbook_id: str
    playbook_version: str
    dry_run_source_plan: dict[str, Any]
    sandbox: bool
    read_only: bool
    executed_at: str
    step_results: tuple[StepExecutionResult, ...]
    status: str
    blocked_reasons: tuple[str, ...]
    provenance: dict[str, Any]
    redaction: SandboxRedactionState
    schema_version: str = SANDBOX_EXECUTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ReadOnlyPlaybookSandbox:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def execute(
        self,
        plan: PlaybookPlan,
        context: dict[str, Any],
        policy: PlaybookSelectionPolicy | None = None,
    ) -> SandboxExecutionRecord:
        executed_at = self.clock()
        if not plan.executable:
            return self._record(
                plan=plan,
                context=context,
                executed_at=executed_at,
                step_results=(),
                status="blocked",
                blocked_reasons=plan.blocked_reasons or ("plan_not_executable",),
                policy=policy,
            )

        step_results = tuple(self.execute_step(step, context, policy=policy) for step in plan.step_plans)
        blocked = tuple(sorted({reason for result in step_results for reason in result.blocked_reasons}))
        if any(result.status == "failed_safe" for result in step_results):
            status = "failed_safe"
        elif blocked or any(result.status == "blocked" for result in step_results):
            status = "blocked"
        elif all(result.status == "skipped" for result in step_results) and step_results:
            status = "skipped"
        else:
            status = "completed"
        return self._record(
            plan=plan,
            context=context,
            executed_at=executed_at,
            step_results=step_results,
            status=status,
            blocked_reasons=blocked,
            policy=policy,
        )

    def execute_step(
        self,
        step_plan: StepPlan,
        context: dict[str, Any],
        policy: PlaybookSelectionPolicy | None = None,
    ) -> StepExecutionResult:
        if step_plan.status == "skipped":
            return StepExecutionResult(
                step_id=step_plan.step_id,
                status="skipped",
                provenance=_step_provenance(step_plan, evaluator_id="skipped"),
            )
        selected_policy = policy or PlaybookSelectionPolicy()
        blockers = list(step_plan.blocked_reasons)
        if step_plan.mutation_required:
            blockers.append("mutation_not_allowed")
        if step_plan.raw_access_required and not (selected_policy.allow_raw_metrics or selected_policy.allow_raw_transcript):
            blockers.append("raw_access_not_allowed")
        missing_capabilities = sorted(set(step_plan.required_capabilities) - set(selected_policy.available_capabilities))
        if missing_capabilities:
            blockers.append("capability_not_available")
        if step_plan.kind not in SUPPORTED_SANDBOX_STEP_KINDS:
            blockers.append("unsupported_step_kind")
        blockers = sorted(set(blockers))
        if blockers:
            return StepExecutionResult(
                step_id=step_plan.step_id,
                status="blocked",
                blocked_reasons=tuple(blockers),
                capability_used=(),
                provenance=_step_provenance(step_plan, evaluator_id="blocked"),
            )
        try:
            output = _evaluate_step(step_plan, context)
        except Exception as exc:  # defensive fail-closed boundary
            return StepExecutionResult(
                step_id=step_plan.step_id,
                status="failed_safe",
                blocked_reasons=("failed_safe",),
                provenance={**_step_provenance(step_plan, evaluator_id=step_plan.kind), "error": exc.__class__.__name__},
            )
        result = StepExecutionResult(
            step_id=step_plan.step_id,
            status="completed",
            output_ref_or_value=output,
            capability_used=tuple(step_plan.required_capabilities),
            raw_access_used=False,
            mutation_used=False,
            side_effects=False,
            provenance=_step_provenance(step_plan, evaluator_id=step_plan.kind),
        )
        _assert_execution_safe(result.to_dict())
        return result

    def explain_execution(self, record: SandboxExecutionRecord) -> tuple[str, ...]:
        return record.blocked_reasons

    def _record(
        self,
        *,
        plan: PlaybookPlan,
        context: dict[str, Any],
        executed_at: str,
        step_results: tuple[StepExecutionResult, ...],
        status: str,
        blocked_reasons: tuple[str, ...],
        policy: PlaybookSelectionPolicy | None,
    ) -> SandboxExecutionRecord:
        record = SandboxExecutionRecord(
            execution_id=_execution_id(plan.plan_id, executed_at),
            plan_id=plan.plan_id,
            playbook_id=plan.playbook_id,
            playbook_version=plan.playbook_version,
            dry_run_source_plan={
                "plan_id": plan.plan_id,
                "schema_version": plan.schema_version,
                "dry_run": plan.dry_run,
                "executed": plan.executed,
            },
            sandbox=True,
            read_only=True,
            executed_at=executed_at,
            step_results=tuple(sorted(step_results, key=lambda item: item.step_id)),
            status=status,
            blocked_reasons=tuple(sorted(set(blocked_reasons))),
            provenance={
                "sandbox_version": READ_ONLY_SANDBOX_VERSION,
                "source_plan_id": plan.plan_id,
                "playbook_id": plan.playbook_id,
                "playbook_version": plan.playbook_version,
                "context_schema_version": str(context.get("schema_version") or ""),
                "context_ref": dict(plan.context_ref),
                "policy_used": _policy_summary(policy),
                "step_evaluator_ids": sorted({result.provenance.get("evaluator_id", "") for result in step_results}),
                "blocked_reasons": tuple(sorted(set(blocked_reasons))),
            },
            redaction=SandboxRedactionState(),
        )
        _assert_execution_safe(record.to_dict())
        return record


def _evaluate_step(step_plan: StepPlan, context: dict[str, Any]) -> dict[str, Any]:
    if step_plan.kind == "inspect_context":
        return {
            "context_schema_version": str(context.get("schema_version") or ""),
            "content_entity_id": str((context.get("content_entity") or {}).get("content_entity_id") or ""),
            "current_revision_id": str((context.get("current_revision") or {}).get("content_revision_id") or ""),
            "publication_count": len(context.get("publications") or ()),
            "metrics_present": bool((context.get("freshness") or {}).get("metrics_present")),
            "transcript_available": bool((context.get("transcript_state") or {}).get("available")),
        }
    if step_plan.kind == "list_publications":
        return {
            "publications": [
                {
                    "publication_id": publication.get("publication_id", ""),
                    "provider": publication.get("provider", ""),
                    "state": publication.get("state", ""),
                    "published_at": publication.get("published_at", ""),
                    "observed_at": publication.get("observed_at", ""),
                }
                for publication in sorted(context.get("publications") or (), key=lambda item: item.get("publication_id", ""))
            ]
        }
    if step_plan.kind == "list_metric_history":
        return {
            "metrics": [
                {
                    "publication_id": publication.get("publication_id", ""),
                    "snapshot_id": snapshot.get("snapshot_id", ""),
                    "observed_at": snapshot.get("observed_at", ""),
                    "metric_keys": sorted((snapshot.get("normalized_metrics") or {}).keys()),
                }
                for publication in sorted(context.get("publications") or (), key=lambda item: item.get("publication_id", ""))
                for snapshot in sorted(publication.get("metrics_history") or (), key=lambda item: item.get("observed_at", ""))
            ]
        }
    if step_plan.kind == "check_transcript_available":
        transcript = context.get("transcript_state") or {}
        return {
            "available": bool(transcript.get("available")),
            "language": transcript.get("language", ""),
            "normalized_artifact_id": transcript.get("normalized_artifact_id", ""),
        }
    if step_plan.kind == "check_metrics_available":
        freshness = context.get("freshness") or {}
        return {
            "available": bool(freshness.get("metrics_present")),
            "latest_metrics_observed_at": freshness.get("latest_metrics_observed_at", ""),
            "snapshot_count": freshness.get("snapshot_count", 0),
        }
    if step_plan.kind == "summarize_available_fields":
        return {
            "available_fields": sorted(
                {
                    "content_entity",
                    "current_revision",
                    "freshness",
                    "publications",
                    "redaction",
                    "schema_version",
                    "transcript_state",
                }
                & set(context.keys())
            )
        }
    return {}


def _step_provenance(step_plan: StepPlan, *, evaluator_id: str) -> dict[str, Any]:
    return {
        "evaluator_id": evaluator_id,
        "step_id": step_plan.step_id,
        "sandbox_version": READ_ONLY_SANDBOX_VERSION,
        "mutation_used": False,
        "raw_access_used": False,
    }


def _execution_id(plan_id: str, executed_at: str) -> str:
    digest = hashlib.sha256(f"{plan_id}:{executed_at}".encode("utf-8")).hexdigest()
    return f"sandbox_execution_{digest[:32]}"


def _policy_summary(policy: PlaybookSelectionPolicy | None) -> dict[str, Any]:
    selected = policy or PlaybookSelectionPolicy()
    return {
        "allow_deprecated": selected.allow_deprecated,
        "allow_mutations": selected.allow_mutations,
        "allow_raw_metrics": selected.allow_raw_metrics,
        "allow_raw_transcript": selected.allow_raw_transcript,
        "available_capabilities": sorted(selected.available_capabilities),
    }


def _assert_execution_safe(payload: dict[str, Any]) -> None:
    if _contains_registry_secret(payload):
        raise PlaybookValidationError("sandbox_execution.secret_value", "Sandbox execution must not contain secrets.")
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "Authorization", "Bearer ", "SECRET_CANARY")
    if any(item in rendered for item in forbidden):
        raise PlaybookValidationError("sandbox_execution.raw_or_secret_value", "Sandbox execution contains forbidden raw data.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
