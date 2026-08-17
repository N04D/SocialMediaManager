from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .approval_request_draft import SAFE_REQUESTED_ACTION_KINDS
from .events import utc_now_iso
from .errors import PlaybookValidationError
from .playbook_registry import _contains_registry_secret
from .promotion_gate import UNSAFE_NEXT_ACTION_MARKERS

EXECUTION_ELIGIBILITY_SCHEMA_VERSION = "execution-eligibility-decision.v1"
EXECUTION_ELIGIBILITY_GATE_VERSION = "execution-eligibility-gate.v1"


@dataclass(frozen=True)
class ExecutionEligibilityPolicy:
    policy_id: str = "execution-eligibility-default"
    version: str = "1.0.0"
    require_promotion_eligible: bool = True
    require_approved: bool = True
    require_scope_match: bool = True
    require_action_match: bool = True
    allow_needs_review: bool = False
    allowed_action_kinds: tuple[str, ...] = SAFE_REQUESTED_ACTION_KINDS
    require_sandbox_execution: bool = True
    require_read_only_sandbox: bool = True
    allow_raw_access: bool = False
    allow_mutations: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionEligibilityReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionEligibilityRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    execution_started: bool = False
    production_mutation_used: bool = False


@dataclass(frozen=True)
class ExecutionEligibilityDecision:
    decision_id: str
    status: str
    subject_execution_id: str
    subject_plan_id: str
    subject_promotion_decision_id: str
    subject_approval_id: str
    requested_action_kind: str
    reasons: tuple[ExecutionEligibilityReason, ...]
    blocked_capabilities: tuple[str, ...]
    matched_scope: dict[str, Any]
    provenance: dict[str, Any]
    redaction: ExecutionEligibilityRedaction
    decided_at: str
    schema_version: str = EXECUTION_ELIGIBILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionEligibilityGate:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def decide(
        self,
        promotion_decision: Any | None,
        approval_request: Any | None,
        *,
        plan: Any | None = None,
        execution_record: Any | None = None,
        policy: ExecutionEligibilityPolicy | None = None,
    ) -> ExecutionEligibilityDecision:
        selected_policy = policy or ExecutionEligibilityPolicy()
        promotion = _payload(promotion_decision)
        approval = _payload(approval_request)
        plan_payload = _payload(plan)
        execution = _payload(execution_record)
        decided_at = self.clock()
        matched_scope = _matched_scope(promotion, approval, plan_payload, execution)
        reasons: list[ExecutionEligibilityReason] = []
        reasons.extend(_promotion_reasons(promotion, selected_policy))
        reasons.extend(_approval_reasons(approval, selected_policy))
        reasons.extend(_action_reasons(approval, selected_policy))
        reasons.extend(_scope_reasons(matched_scope, selected_policy))
        reasons.extend(_execution_reasons(execution, selected_policy))
        reasons.extend(_redaction_reasons(promotion, approval, execution, selected_policy))
        reasons = sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code))
        status = _status(reasons)
        requested_action_kind = str(approval.get("requested_action_kind") or "")
        safe_requested_action_kind = (
            requested_action_kind if requested_action_kind in SAFE_REQUESTED_ACTION_KINDS else "unsupported"
        )
        decision = ExecutionEligibilityDecision(
            decision_id=_decision_id(promotion, approval, plan_payload, execution, selected_policy, decided_at),
            status=status,
            subject_execution_id=str(
                execution.get("execution_id")
                or approval.get("scope", {}).get("execution_id")
                or promotion.get("subject_execution_id")
                or ""
            ),
            subject_plan_id=str(plan_payload.get("plan_id") or ""),
            subject_promotion_decision_id=str(promotion.get("decision_id") or approval.get("scope", {}).get("decision_id") or ""),
            subject_approval_id=str(approval.get("approval_id") or ""),
            requested_action_kind=safe_requested_action_kind,
            reasons=tuple(reasons),
            blocked_capabilities=_blocked_capabilities(promotion, reasons),
            matched_scope=matched_scope,
            provenance=_provenance(promotion, approval, plan_payload, execution, selected_policy),
            redaction=ExecutionEligibilityRedaction(),
            decided_at=decided_at,
        )
        _assert_decision_safe(decision.to_dict())
        return decision

    def explain(self, decision: ExecutionEligibilityDecision) -> tuple[str, ...]:
        return tuple(reason.reason_code for reason in decision.reasons)

    def is_eligible(self, decision: ExecutionEligibilityDecision) -> bool:
        return decision.status == "eligible"


def _promotion_reasons(promotion: dict[str, Any], policy: ExecutionEligibilityPolicy) -> list[ExecutionEligibilityReason]:
    if not promotion:
        return [_error("promotion_missing", "promotion")]
    status = str(promotion.get("status") or "")
    if status == "eligible":
        return []
    if status == "needs_review" and policy.allow_needs_review:
        return [_warning("promotion_needs_review", "promotion.status")]
    if status == "needs_review":
        return [_error("promotion_needs_review_blocked", "promotion.status")]
    return [_error("promotion_not_eligible", "promotion.status", {"status": status})]


def _approval_reasons(approval: dict[str, Any], policy: ExecutionEligibilityPolicy) -> list[ExecutionEligibilityReason]:
    if not approval:
        return [_error("approval_missing", "approval")]
    status = str(approval.get("status") or "")
    if policy.require_approved and status != "approved":
        return [_error(f"approval_{status or 'missing'}_blocks", "approval.status")]
    return []


def _action_reasons(approval: dict[str, Any], policy: ExecutionEligibilityPolicy) -> list[ExecutionEligibilityReason]:
    if not approval:
        return []
    action_kind = str(approval.get("requested_action_kind") or "")
    action_text = f"{approval.get('requested_action') or ''} {action_kind}"
    reasons: list[ExecutionEligibilityReason] = []
    if action_kind not in SAFE_REQUESTED_ACTION_KINDS or any(marker in action_text for marker in UNSAFE_NEXT_ACTION_MARKERS):
        reasons.append(_error("unsafe_action_kind", "approval.requested_action_kind"))
    elif action_kind not in policy.allowed_action_kinds:
        reasons.append(_error("action_kind_not_allowed", "approval.requested_action_kind"))
    scope_kind = str((approval.get("scope") or {}).get("requested_action_kind") or "")
    if policy.require_action_match and scope_kind and scope_kind != action_kind:
        reasons.append(_error("action_mismatch", "approval.scope.requested_action_kind"))
    return reasons


def _scope_reasons(scope: dict[str, Any], policy: ExecutionEligibilityPolicy) -> list[ExecutionEligibilityReason]:
    if not policy.require_scope_match:
        return []
    reasons = []
    required = ("decision_matches", "execution_matches")
    for key in required:
        if scope.get(key) is False:
            reasons.append(_error("scope_mismatch", f"scope.{key}"))
    for key in ("playbook_id_matches", "playbook_version_matches"):
        if scope.get(key) is False:
            reasons.append(_error("scope_mismatch", f"scope.{key}"))
    return reasons


def _execution_reasons(execution: dict[str, Any], policy: ExecutionEligibilityPolicy) -> list[ExecutionEligibilityReason]:
    if not execution:
        return [_error("execution_missing", "execution")] if policy.require_sandbox_execution else []
    reasons: list[ExecutionEligibilityReason] = []
    if policy.require_sandbox_execution and execution.get("sandbox") is not True:
        reasons.append(_error("execution_not_sandbox", "execution.sandbox"))
    if policy.require_read_only_sandbox and execution.get("read_only") is not True:
        reasons.append(_error("execution_not_read_only", "execution.read_only"))
    for step in execution.get("step_results") or ():
        step_ref = f"step:{step.get('step_id', '')}"
        if step.get("mutation_used") is not False and not policy.allow_mutations:
            reasons.append(_error("mutation_used", step_ref))
        if step.get("raw_access_used") is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_access_used", step_ref))
    if _marker_present(execution, ("production_executor_invoked", "ai_invoked", "llm_call", "interactive_collection_invoked", "network_invoked")):
        reasons.append(_error("forbidden_execution_marker", "execution.provenance"))
    return reasons


def _redaction_reasons(
    promotion: dict[str, Any],
    approval: dict[str, Any],
    execution: dict[str, Any],
    policy: ExecutionEligibilityPolicy,
) -> list[ExecutionEligibilityReason]:
    reasons = []
    for label, payload in (("promotion", promotion), ("approval", approval), ("execution", execution)):
        if not payload:
            continue
        redaction = payload.get("redaction") or {}
        if redaction.get("secrets_included") is not False or redaction.get("provider_headers_included") is not False:
            reasons.append(_error("unsafe_redaction", f"{label}.redaction"))
        if redaction.get("raw_metrics_included") is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_metrics_included", f"{label}.redaction"))
        if redaction.get("raw_transcript_included") is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_transcript_included", f"{label}.redaction"))
        if redaction.get("execution_started") is True or redaction.get("production_mutation_used") is True:
            reasons.append(_error("forbidden_side_effect", f"{label}.redaction"))
        if _contains_forbidden_data(payload):
            reasons.append(_error("forbidden_data_present", label))
    return reasons


def _matched_scope(
    promotion: dict[str, Any],
    approval: dict[str, Any],
    plan: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    scope = approval.get("scope") or {}
    decision_id = str(promotion.get("decision_id") or "")
    execution_id = str(execution.get("execution_id") or promotion.get("subject_execution_id") or "")
    playbook_id = str(plan.get("playbook_id") or execution.get("playbook_id") or "")
    playbook_version = str(plan.get("playbook_version") or execution.get("playbook_version") or "")
    result = {
        "decision_id": str(scope.get("decision_id") or ""),
        "decision_matches": _matches(scope.get("decision_id"), decision_id),
        "execution_id": str(scope.get("execution_id") or ""),
        "execution_matches": _matches(scope.get("execution_id"), execution_id),
        "packet_id": str(scope.get("packet_id") or approval.get("packet_id") or ""),
        "playbook_id": str(scope.get("playbook_id") or ""),
        "playbook_id_matches": _matches(scope.get("playbook_id"), playbook_id),
        "playbook_version": str(scope.get("playbook_version") or ""),
        "playbook_version_matches": _matches(scope.get("playbook_version"), playbook_version),
        "requested_action_kind": str(scope.get("requested_action_kind") or ""),
    }
    return dict(sorted(result.items()))


def _matches(scope_value: Any, actual: str) -> bool | None:
    rendered = str(scope_value or "")
    if not rendered:
        return None
    if not actual:
        return None
    return rendered == actual


def _status(reasons: list[ExecutionEligibilityReason]) -> str:
    if any(reason.severity == "error" for reason in reasons):
        return "blocked"
    if any(reason.severity == "warning" for reason in reasons):
        return "needs_review"
    return "eligible"


def _blocked_capabilities(promotion: dict[str, Any], reasons: list[ExecutionEligibilityReason]) -> tuple[str, ...]:
    blocked = set(str(item) for item in promotion.get("blocked_capabilities") or () if str(item))
    if any(reason.reason_code in {"mutation_used", "raw_access_used"} for reason in reasons):
        blocked.add("execution.side_effect")
    return tuple(sorted(blocked))


def _provenance(
    promotion: dict[str, Any],
    approval: dict[str, Any],
    plan: dict[str, Any],
    execution: dict[str, Any],
    policy: ExecutionEligibilityPolicy,
) -> dict[str, Any]:
    return dict(sorted({
        "gate_version": EXECUTION_ELIGIBILITY_GATE_VERSION,
        "approval_ref": _ref(approval, "approval_id", "schema_version"),
        "execution_ref": _ref(execution, "execution_id", "schema_version"),
        "plan_ref": _ref(plan, "plan_id", "schema_version"),
        "policy": policy.to_dict(),
        "promotion_ref": _ref(promotion, "decision_id", "schema_version"),
    }.items()))


def _ref(payload: dict[str, Any], id_key: str, schema_key: str) -> dict[str, str]:
    if not payload:
        return {}
    return {"id": str(payload.get(id_key) or ""), "schema_version": str(payload.get(schema_key) or "")}


def _decision_id(
    promotion: dict[str, Any],
    approval: dict[str, Any],
    plan: dict[str, Any],
    execution: dict[str, Any],
    policy: ExecutionEligibilityPolicy,
    decided_at: str,
) -> str:
    seed = {
        "approval_id": approval.get("approval_id") or "",
        "decided_at": decided_at,
        "execution_id": execution.get("execution_id") or "",
        "plan_id": plan.get("plan_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "promotion_decision_id": promotion.get("decision_id") or "",
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"execution_eligibility_{digest[:32]}"


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionEligibilityReason:
    return ExecutionEligibilityReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _warning(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionEligibilityReason:
    return ExecutionEligibilityReason(reason_code=reason_code, severity="warning", subject_ref=subject_ref, details=details or {})


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    if _contains_registry_secret(payload):
        return True
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    return any(item in rendered for item in forbidden)


def _marker_present(payload: dict[str, Any], markers: tuple[str, ...]) -> bool:
    rendered = json.dumps(payload, sort_keys=True).lower()
    return any(marker.lower() in rendered for marker in markers)


def _assert_decision_safe(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    action_text = str(payload.get("requested_action_kind") or "")
    if _contains_forbidden_data(payload) or any(marker in action_text for marker in UNSAFE_NEXT_ACTION_MARKERS):
        raise PlaybookValidationError(
            "execution_eligibility.unsafe_payload",
            "Execution eligibility decision contains unsafe data.",
        )
    redaction = payload.get("redaction") or {}
    if redaction.get("approval_state_mutated") is not False or redaction.get("execution_started") is not False:
        raise PlaybookValidationError(
            "execution_eligibility.side_effect",
            "Execution eligibility decision recorded a forbidden side effect.",
        )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
