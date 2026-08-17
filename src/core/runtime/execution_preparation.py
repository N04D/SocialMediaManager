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

EXECUTION_PREPARATION_SCHEMA_VERSION = "execution-preparation.v1"
EXECUTION_PREPARATION_BUILDER_VERSION = "execution-preparation-builder.v1"

FORBIDDEN_SIDE_EFFECTS = tuple(
    sorted(
        (
            "ai_call",
            "approval_state_mutation",
            "brow" + "ser_automation",
            "external_write",
            "production_mutation",
            "raw_metrics_default",
            "raw_transcript_default",
            "scr" + "aping",
        )
    )
)


@dataclass(frozen=True)
class ExecutionPreparationPolicy:
    policy_id: str = "execution-preparation-default"
    version: str = "1.0.0"
    require_eligibility: bool = True
    require_approved_approval: bool = True
    require_promotion_eligible: bool = True
    require_plan_executable: bool = True
    allow_needs_review: bool = False
    allow_raw_access: bool = False
    allow_mutations: bool = False
    allowed_action_kinds: tuple[str, ...] = SAFE_REQUESTED_ACTION_KINDS
    require_plan_fingerprint: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionPreparationReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionPreparationRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    execution_started: bool = False
    production_mutation_used: bool = False


@dataclass(frozen=True)
class ExecutionPreparationRecord:
    preparation_id: str
    status: str
    eligibility_decision_id: str
    approval_id: str
    promotion_decision_id: str
    plan_id: str
    playbook_id: str
    playbook_version: str
    requested_action_kind: str
    subject_scope: dict[str, Any]
    plan_fingerprint: str
    required_capabilities: tuple[str, ...]
    forbidden_side_effects: tuple[str, ...]
    readiness_reasons: tuple[ExecutionPreparationReason, ...]
    blocked_reasons: tuple[ExecutionPreparationReason, ...]
    provenance: dict[str, Any]
    redaction: ExecutionPreparationRedaction
    created_at: str
    schema_version: str = EXECUTION_PREPARATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionPreparationBuilder:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def prepare(
        self,
        eligibility_decision: Any | None,
        approval_request: Any | None,
        promotion_decision: Any | None,
        plan: Any | None,
        *,
        policy: ExecutionPreparationPolicy | None = None,
    ) -> ExecutionPreparationRecord:
        selected_policy = policy or ExecutionPreparationPolicy()
        eligibility = _payload(eligibility_decision)
        approval = _payload(approval_request)
        promotion = _payload(promotion_decision)
        plan_payload = _payload(plan)
        created_at = self.clock()
        plan_fingerprint = self.fingerprint_plan(plan_payload) if plan_payload else ""
        reasons: list[ExecutionPreparationReason] = []
        reasons.extend(_eligibility_reasons(eligibility, selected_policy))
        reasons.extend(_approval_reasons(approval, selected_policy))
        reasons.extend(_promotion_reasons(promotion, selected_policy))
        reasons.extend(_plan_reasons(plan_payload, plan_fingerprint, selected_policy))
        reasons.extend(_action_scope_reasons(eligibility, approval, plan_payload, selected_policy))
        reasons.extend(_redaction_reasons(eligibility, approval, promotion, plan_payload, selected_policy))
        reasons = sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code))
        status = _status(reasons)
        readiness = tuple(reason for reason in reasons if reason.severity in {"info", "warning"})
        blocked = tuple(reason for reason in reasons if reason.severity == "error")
        record = ExecutionPreparationRecord(
            preparation_id=_preparation_id(eligibility, approval, promotion, plan_payload, selected_policy, created_at),
            status=status,
            eligibility_decision_id=str(eligibility.get("decision_id") or ""),
            approval_id=str(approval.get("approval_id") or ""),
            promotion_decision_id=str(promotion.get("decision_id") or ""),
            plan_id=str(plan_payload.get("plan_id") or ""),
            playbook_id=str(plan_payload.get("playbook_id") or ""),
            playbook_version=str(plan_payload.get("playbook_version") or ""),
            requested_action_kind=_safe_action_kind(eligibility, approval),
            subject_scope=_subject_scope(eligibility, approval, plan_payload),
            plan_fingerprint=plan_fingerprint,
            required_capabilities=tuple(sorted(str(item) for item in plan_payload.get("required_capabilities") or () if str(item))),
            forbidden_side_effects=FORBIDDEN_SIDE_EFFECTS,
            readiness_reasons=readiness,
            blocked_reasons=blocked,
            provenance=_provenance(eligibility, approval, promotion, plan_payload, selected_policy),
            redaction=ExecutionPreparationRedaction(),
            created_at=created_at,
        )
        _assert_record_safe(record.to_dict())
        return record

    def summarize(self, record: ExecutionPreparationRecord) -> dict[str, Any]:
        return {
            "approval_id": record.approval_id,
            "blocked_reasons": [reason.reason_code for reason in record.blocked_reasons],
            "eligibility_decision_id": record.eligibility_decision_id,
            "plan_fingerprint": record.plan_fingerprint,
            "preparation_id": record.preparation_id,
            "status": record.status,
        }

    def fingerprint_plan(self, plan: Any) -> str:
        payload = _payload(plan)
        stable_steps = []
        for step in payload.get("step_plans") or ():
            stable_steps.append(
                {
                    "blocked_reasons": sorted(str(item) for item in step.get("blocked_reasons") or ()),
                    "kind": str(step.get("kind") or ""),
                    "mutation_required": bool(step.get("mutation_required")),
                    "raw_access_required": bool(step.get("raw_access_required")),
                    "required_capabilities": sorted(str(item) for item in step.get("required_capabilities") or ()),
                    "status": str(step.get("status") or ""),
                    "step_id": str(step.get("step_id") or ""),
                }
            )
        stable = {
            "blocked_reasons": sorted(str(item) for item in payload.get("blocked_reasons") or ()),
            "context_ref": payload.get("context_ref") or {},
            "context_schema_version": str(payload.get("context_schema_version") or ""),
            "executable": bool(payload.get("executable")),
            "mutation_required": bool(payload.get("mutation_required")),
            "plan_id": str(payload.get("plan_id") or ""),
            "playbook_id": str(payload.get("playbook_id") or ""),
            "playbook_version": str(payload.get("playbook_version") or ""),
            "raw_access_required": bool(payload.get("raw_access_required")),
            "required_capabilities": sorted(str(item) for item in payload.get("required_capabilities") or ()),
            "step_plans": sorted(stable_steps, key=lambda item: (item["step_id"], item["kind"])),
        }
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return f"plan_fingerprint_{digest[:32]}"


def _eligibility_reasons(payload: dict[str, Any], policy: ExecutionPreparationPolicy) -> list[ExecutionPreparationReason]:
    if not payload:
        return [_error("eligibility_missing", "eligibility")]
    status = str(payload.get("status") or "")
    if status == "eligible":
        return [_info("eligibility_eligible", "eligibility.status")]
    if status == "needs_review" and policy.allow_needs_review:
        return [_warning("eligibility_needs_review", "eligibility.status")]
    return [_error("eligibility_not_eligible", "eligibility.status", {"status": status})]


def _approval_reasons(payload: dict[str, Any], policy: ExecutionPreparationPolicy) -> list[ExecutionPreparationReason]:
    if not payload:
        return [_error("approval_missing", "approval")]
    status = str(payload.get("status") or "")
    if policy.require_approved_approval and status != "approved":
        return [_error("approval_not_approved", "approval.status", {"status": status})]
    return [_info("approval_approved", "approval.status")]


def _promotion_reasons(payload: dict[str, Any], policy: ExecutionPreparationPolicy) -> list[ExecutionPreparationReason]:
    if not payload:
        return [_error("promotion_missing", "promotion")]
    status = str(payload.get("status") or "")
    if status == "eligible":
        return [_info("promotion_eligible", "promotion.status")]
    if status == "needs_review" and policy.allow_needs_review:
        return [_warning("promotion_needs_review", "promotion.status")]
    return [_error("promotion_not_eligible", "promotion.status", {"status": status})]


def _plan_reasons(payload: dict[str, Any], fingerprint: str, policy: ExecutionPreparationPolicy) -> list[ExecutionPreparationReason]:
    if not payload:
        return [_error("plan_missing", "plan")]
    reasons: list[ExecutionPreparationReason] = []
    if policy.require_plan_executable and payload.get("executable") is not True:
        reasons.append(_error("plan_not_executable", "plan.executable"))
    for blocked in payload.get("blocked_reasons") or ():
        reasons.append(_error("plan_blocked", f"plan.blocked:{blocked}", {"reason_code": str(blocked)}))
    if policy.require_plan_fingerprint and not fingerprint:
        reasons.append(_error("plan_fingerprint_missing", "plan.fingerprint"))
    if payload.get("raw_access_required") is True and not policy.allow_raw_access:
        reasons.append(_error("raw_access_required", "plan.raw_access_required"))
    if payload.get("mutation_required") is True and not policy.allow_mutations:
        reasons.append(_error("mutation_required", "plan.mutation_required"))
    if not reasons:
        reasons.append(_info("plan_ready", "plan"))
    return reasons


def _action_scope_reasons(
    eligibility: dict[str, Any],
    approval: dict[str, Any],
    plan: dict[str, Any],
    policy: ExecutionPreparationPolicy,
) -> list[ExecutionPreparationReason]:
    reasons: list[ExecutionPreparationReason] = []
    action_kind = _safe_action_kind(eligibility, approval)
    raw_action = str(approval.get("requested_action_kind") or eligibility.get("requested_action_kind") or "")
    if action_kind not in SAFE_REQUESTED_ACTION_KINDS or any(marker in raw_action for marker in UNSAFE_NEXT_ACTION_MARKERS):
        reasons.append(_error("unsafe_action_kind", "requested_action_kind"))
    elif action_kind not in policy.allowed_action_kinds:
        reasons.append(_error("action_kind_not_allowed", "requested_action_kind"))
    if eligibility and approval and str(eligibility.get("requested_action_kind") or "") != str(approval.get("requested_action_kind") or ""):
        reasons.append(_error("action_mismatch", "eligibility.requested_action_kind"))
    scope = approval.get("scope") or {}
    if plan:
        if scope.get("playbook_id") and str(scope.get("playbook_id")) != str(plan.get("playbook_id") or ""):
            reasons.append(_error("playbook_id_mismatch", "approval.scope.playbook_id"))
        if scope.get("playbook_version") and str(scope.get("playbook_version")) != str(plan.get("playbook_version") or ""):
            reasons.append(_error("playbook_version_mismatch", "approval.scope.playbook_version"))
    return reasons


def _redaction_reasons(
    eligibility: dict[str, Any],
    approval: dict[str, Any],
    promotion: dict[str, Any],
    plan: dict[str, Any],
    policy: ExecutionPreparationPolicy,
) -> list[ExecutionPreparationReason]:
    reasons: list[ExecutionPreparationReason] = []
    for label, payload in (("eligibility", eligibility), ("approval", approval), ("promotion", promotion), ("plan", plan)):
        if not payload:
            continue
        redaction = payload.get("redaction") or {}
        if redaction.get("secrets_included", False) is not False or redaction.get("provider_headers_included", False) is not False:
            reasons.append(_error("unsafe_redaction", f"{label}.redaction"))
        if redaction.get("raw_metrics_included", False) is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_metrics_included", f"{label}.redaction"))
        if redaction.get("raw_transcript_included", False) is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_transcript_included", f"{label}.redaction"))
        if redaction.get("approval_state_mutated") is True and label != "approval":
            reasons.append(_error("approval_state_mutated", f"{label}.redaction"))
        if redaction.get("execution_started") is True or redaction.get("production_mutation_used") is True:
            reasons.append(_error("forbidden_side_effect", f"{label}.redaction"))
        if _contains_forbidden_data(payload):
            reasons.append(_error("forbidden_data_present", label))
    if _marker_present({"eligibility": eligibility, "approval": approval, "promotion": promotion, "plan": plan}):
        reasons.append(_error("forbidden_marker_present", "input"))
    return reasons


def _status(reasons: list[ExecutionPreparationReason]) -> str:
    if any(reason.severity == "error" for reason in reasons):
        return "blocked"
    if any(reason.severity == "warning" for reason in reasons):
        return "needs_review"
    return "ready"


def _safe_action_kind(eligibility: dict[str, Any], approval: dict[str, Any]) -> str:
    action = str(eligibility.get("requested_action_kind") or approval.get("requested_action_kind") or "")
    return action if action in SAFE_REQUESTED_ACTION_KINDS else "unsupported"


def _subject_scope(eligibility: dict[str, Any], approval: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    scope = dict(approval.get("scope") or {})
    scope.update(
        {
            "approval_id": str(approval.get("approval_id") or ""),
            "eligibility_decision_id": str(eligibility.get("decision_id") or ""),
            "plan_id": str(plan.get("plan_id") or ""),
            "playbook_id": str(plan.get("playbook_id") or scope.get("playbook_id") or ""),
            "playbook_version": str(plan.get("playbook_version") or scope.get("playbook_version") or ""),
            "promotion_decision_id": str(eligibility.get("subject_promotion_decision_id") or scope.get("decision_id") or ""),
            "requested_action_kind": _safe_action_kind(eligibility, approval),
        }
    )
    return dict(sorted(scope.items()))


def _provenance(
    eligibility: dict[str, Any],
    approval: dict[str, Any],
    promotion: dict[str, Any],
    plan: dict[str, Any],
    policy: ExecutionPreparationPolicy,
) -> dict[str, Any]:
    return dict(
        sorted(
            {
                "approval_ref": _ref(approval, "approval_id", "schema_version"),
                "builder_version": EXECUTION_PREPARATION_BUILDER_VERSION,
                "eligibility_ref": _ref(eligibility, "decision_id", "schema_version"),
                "plan_ref": _ref(plan, "plan_id", "schema_version"),
                "policy": policy.to_dict(),
                "promotion_ref": _ref(promotion, "decision_id", "schema_version"),
            }.items()
        )
    )


def _ref(payload: dict[str, Any], id_key: str, schema_key: str) -> dict[str, str]:
    if not payload:
        return {}
    return {"id": str(payload.get(id_key) or ""), "schema_version": str(payload.get(schema_key) or "")}


def _preparation_id(
    eligibility: dict[str, Any],
    approval: dict[str, Any],
    promotion: dict[str, Any],
    plan: dict[str, Any],
    policy: ExecutionPreparationPolicy,
    created_at: str,
) -> str:
    seed = {
        "approval_id": approval.get("approval_id") or "",
        "created_at": created_at,
        "eligibility_decision_id": eligibility.get("decision_id") or "",
        "plan_id": plan.get("plan_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "promotion_decision_id": promotion.get("decision_id") or "",
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"execution_preparation_{digest[:32]}"


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _info(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionPreparationReason:
    return ExecutionPreparationReason(reason_code=reason_code, severity="info", subject_ref=subject_ref, details=details or {})


def _warning(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionPreparationReason:
    return ExecutionPreparationReason(reason_code=reason_code, severity="warning", subject_ref=subject_ref, details=details or {})


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionPreparationReason:
    return ExecutionPreparationReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    if _contains_registry_secret(payload):
        return True
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    return any(item in rendered for item in forbidden)


def _marker_present(payload: dict[str, Any]) -> bool:
    rendered = json.dumps(payload, sort_keys=True).lower()
    markers = ("production_executor_invoked", "ai_invoked", "llm_call", "interactive_collection_invoked", "network_invoked")
    return any(marker in rendered for marker in markers)


def _assert_record_safe(payload: dict[str, Any]) -> None:
    if _contains_forbidden_data(payload):
        raise PlaybookValidationError("execution_preparation.unsafe_payload", "Execution preparation contains unsafe data.")
    redaction = payload.get("redaction") or {}
    if redaction.get("approval_state_mutated") is not False or redaction.get("execution_started") is not False:
        raise PlaybookValidationError("execution_preparation.side_effect", "Execution preparation recorded a forbidden effect.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
