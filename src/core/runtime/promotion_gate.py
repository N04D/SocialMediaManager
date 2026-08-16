from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .events import utc_now_iso
from .errors import PlaybookValidationError
from .playbook_registry import _contains_registry_secret

PROMOTION_DECISION_SCHEMA_VERSION = "promotion-decision.v1"
PROMOTION_GATE_VERSION = "sandbox-promotion-gate.v1"

SAFE_NEXT_ACTIONS = (
    "allow_manual_review",
    "allow_prepare_approval_request",
    "allow_read_only_agent_consumption",
    "allow_sandbox_replay",
)
UNSAFE_NEXT_ACTION_MARKERS = ("execute_production", "publish", "mutate", "send", "call_ai")


@dataclass(frozen=True)
class PromotionPolicy:
    policy_id: str = "sandbox-promotion-default"
    version: str = "1.0.0"
    require_evaluation_passed: bool = True
    allow_warnings: bool = False
    require_replay_match: bool = False
    allow_blocked_execution: bool = False
    allow_raw_access: bool = False
    allow_mutations: bool = False
    require_manual_review_for_warnings: bool = True
    required_checks: tuple[str, ...] = field(default_factory=tuple)
    forbidden_reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class PromotionReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class PromotionRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False


@dataclass(frozen=True)
class PromotionDecision:
    decision_id: str
    subject_execution_id: str
    subject_evaluation_id: str
    status: str
    reasons: tuple[PromotionReason, ...]
    required_reviews: tuple[str, ...]
    policy_id: str
    policy_version: str
    eligible_next_actions: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    provenance: dict[str, Any]
    redaction: PromotionRedaction
    decided_at: str
    schema_version: str = PROMOTION_DECISION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class PromotionGate:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def decide(
        self,
        evaluation: Any,
        *,
        execution_record: Any | None = None,
        plan: Any | None = None,
        policy: PromotionPolicy | None = None,
    ) -> PromotionDecision:
        selected_policy = policy or PromotionPolicy()
        evaluation_payload = _payload(evaluation)
        execution_payload = _payload(execution_record) if execution_record is not None else {}
        plan_payload = _payload(plan) if plan is not None else {}
        decided_at = self.clock()
        reasons = []
        reasons.extend(_evaluation_reasons(evaluation_payload, selected_policy))
        reasons.extend(_execution_reasons(execution_payload, selected_policy))
        reasons.extend(_plan_reasons(plan_payload))
        reasons = tuple(sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code)))
        required_reviews = _required_reviews(reasons, evaluation_payload, plan_payload, selected_policy)
        status = _decision_status(reasons, required_reviews, evaluation_payload, selected_policy)
        decision = PromotionDecision(
            decision_id=_decision_id(evaluation_payload, execution_payload, selected_policy, decided_at),
            subject_execution_id=str(
                evaluation_payload.get("execution_id") or execution_payload.get("execution_id") or ""
            ),
            subject_evaluation_id=str(evaluation_payload.get("evaluation_id") or ""),
            status=status,
            reasons=reasons,
            required_reviews=tuple(sorted(required_reviews)),
            policy_id=selected_policy.policy_id,
            policy_version=selected_policy.version,
            eligible_next_actions=_eligible_next_actions(status),
            blocked_capabilities=_blocked_capabilities(reasons, execution_payload),
            provenance={
                "promotion_gate_version": PROMOTION_GATE_VERSION,
                "evaluation_schema_version": str(evaluation_payload.get("schema_version") or ""),
                "execution_schema_version": str(execution_payload.get("schema_version") or ""),
                "plan_schema_version": str(plan_payload.get("schema_version") or ""),
                "policy": selected_policy.to_dict(),
            },
            redaction=PromotionRedaction(),
            decided_at=decided_at,
        )
        _assert_decision_safe(decision.to_dict())
        return decision

    def explain(self, decision: PromotionDecision) -> tuple[str, ...]:
        return tuple(reason.reason_code for reason in decision.reasons)

    def is_eligible(self, decision: PromotionDecision) -> bool:
        return decision.status == "eligible"


def _evaluation_reasons(payload: dict[str, Any], policy: PromotionPolicy) -> list[PromotionReason]:
    reasons: list[PromotionReason] = []
    status = str(payload.get("status") or "")
    if not payload:
        return [_error("evaluation_missing", "evaluation")]
    if policy.require_evaluation_passed and status != "passed":
        if status == "warning" and policy.require_manual_review_for_warnings and policy.allow_warnings:
            reasons.append(_warning("evaluation_warning_needs_review", "evaluation"))
        else:
            reasons.append(_error("evaluation_not_passed", "evaluation", {"status": status}))
    elif status == "warning":
        if policy.require_manual_review_for_warnings:
            reasons.append(_warning("evaluation_warning_needs_review", "evaluation"))
        elif not policy.allow_warnings:
            reasons.append(_error("evaluation_warning_blocked", "evaluation"))
    failures = tuple(sorted(str(item) for item in payload.get("failures") or () if str(item)))
    warnings = tuple(sorted(str(item) for item in payload.get("warnings") or () if str(item)))
    for reason in failures:
        reasons.append(_error(reason, "evaluation.failures"))
    for reason in warnings:
        if reason in policy.forbidden_reason_codes:
            reasons.append(_error("forbidden_reason_code", f"evaluation.warning:{reason}", {"reason_code": reason}))
        elif policy.require_manual_review_for_warnings:
            reasons.append(_warning(reason, "evaluation.warnings"))
    check_ids = {str(check.get("check_id") or "") for check in payload.get("checks") or ()}
    for check_id in sorted(policy.required_checks):
        if check_id not in check_ids:
            reasons.append(_warning("required_check_missing", f"check:{check_id}", {"check_id": check_id}))
    for check in payload.get("checks") or ():
        reason_code = str(check.get("reason_code") or "")
        severity = str(check.get("severity") or "")
        subject_ref = str(check.get("subject_ref") or "check")
        if reason_code in policy.forbidden_reason_codes:
            reasons.append(_error("forbidden_reason_code", subject_ref, {"reason_code": reason_code}))
        if severity == "error" or check.get("status") == "failed":
            reasons.append(_error(reason_code or "check_failed", subject_ref))
    if _contains_forbidden_data(payload) or _marker_present(payload, ("production_executor_invoked", "ai_invoked", "interactive_collection_invoked")):
        reasons.append(_error("unsafe_evaluation_payload", "evaluation"))
    return reasons


def _execution_reasons(payload: dict[str, Any], policy: PromotionPolicy) -> list[PromotionReason]:
    if not payload:
        return []
    reasons: list[PromotionReason] = []
    if payload.get("sandbox") is not True:
        reasons.append(_error("execution_not_sandbox", "execution"))
    if payload.get("read_only") is not True:
        reasons.append(_error("execution_not_read_only", "execution"))
    if str(payload.get("status") or "") == "blocked" and not policy.allow_blocked_execution:
        reasons.append(_error("blocked_execution_not_allowed", "execution"))
    redaction = payload.get("redaction") or {}
    if redaction.get("secrets_included") is not False:
        reasons.append(_error("secrets_included", "execution.redaction"))
    if redaction.get("provider_headers_included") is not False:
        reasons.append(_error("provider_headers_included", "execution.redaction"))
    if redaction.get("raw_metrics_included") is not False and not policy.allow_raw_access:
        reasons.append(_error("raw_metrics_included", "execution.redaction"))
    if redaction.get("raw_transcript_included") is not False and not policy.allow_raw_access:
        reasons.append(_error("raw_transcript_included", "execution.redaction"))
    for step in payload.get("step_results") or ():
        step_ref = f"step:{step.get('step_id', '')}"
        if step.get("mutation_used") is not False and not policy.allow_mutations:
            reasons.append(_error("mutation_used", step_ref))
        if step.get("raw_access_used") is not False and not policy.allow_raw_access:
            reasons.append(_error("raw_access_used", step_ref))
    if policy.require_replay_match:
        replay = payload.get("replay") or payload.get("replay_result") or {}
        if not replay or replay.get("matched") is not True:
            reasons.append(_error("replay_match_required", "execution.replay"))
    if _contains_forbidden_data(payload):
        reasons.append(_error("forbidden_data_present", "execution"))
    if _marker_present(payload, ("production_executor_invoked",)):
        reasons.append(_error("production_executor_invoked", "execution.provenance"))
    if _marker_present(payload, ("ai_invoked", "llm_call")):
        reasons.append(_error("ai_invoked", "execution.provenance"))
    if _marker_present(payload, ("interactive_collection_invoked",)):
        reasons.append(_error("interactive_collection_invoked", "execution.provenance"))
    return reasons


def _plan_reasons(payload: dict[str, Any]) -> list[PromotionReason]:
    if not payload:
        return []
    reasons: list[PromotionReason] = []
    selection = payload.get("selection_result") or {}
    selected = selection.get("selected") or []
    if any(str(item.get("status") or "") == "deprecated" for item in selected if isinstance(item, dict)):
        reasons.append(_warning("deprecated_playbook_used", "plan.selection"))
    return reasons


def _decision_status(
    reasons: tuple[PromotionReason, ...],
    required_reviews: tuple[str, ...],
    evaluation: dict[str, Any],
    policy: PromotionPolicy,
) -> str:
    if any(reason.severity == "error" for reason in reasons):
        return "blocked"
    if required_reviews:
        return "needs_review"
    if (evaluation.get("status") == "warning" and not policy.allow_warnings):
        return "blocked"
    return "eligible"


def _required_reviews(
    reasons: tuple[PromotionReason, ...],
    evaluation: dict[str, Any],
    plan: dict[str, Any],
    policy: PromotionPolicy,
) -> tuple[str, ...]:
    reviews = set()
    if policy.require_manual_review_for_warnings and (
        evaluation.get("status") == "warning" or any(reason.severity == "warning" for reason in reasons)
    ):
        reviews.add("manual_review")
    if any(reason.reason_code == "deprecated_playbook_used" for reason in reasons):
        reviews.add("deprecated_playbook_review")
    if any(reason.reason_code == "required_check_missing" for reason in reasons):
        reviews.add("policy_check_review")
    return tuple(sorted(reviews))


def _eligible_next_actions(status: str) -> tuple[str, ...]:
    if status == "eligible":
        return tuple(sorted(("allow_read_only_agent_consumption", "allow_sandbox_replay")))
    if status == "needs_review":
        return tuple(sorted(("allow_manual_review", "allow_prepare_approval_request", "allow_sandbox_replay")))
    return ("allow_sandbox_replay",)


def _blocked_capabilities(reasons: tuple[PromotionReason, ...], execution: dict[str, Any]) -> tuple[str, ...]:
    blocked = set()
    if any(reason.reason_code in {"mutation_used", "raw_access_used"} for reason in reasons):
        for step in execution.get("step_results") or ():
            blocked.update(str(item) for item in step.get("capability_used") or () if str(item))
    return tuple(sorted(blocked))


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> PromotionReason:
    return PromotionReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _warning(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> PromotionReason:
    return PromotionReason(reason_code=reason_code, severity="warning", subject_ref=subject_ref, details=details or {})


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _decision_id(evaluation: dict[str, Any], execution: dict[str, Any], policy: PromotionPolicy, decided_at: str) -> str:
    payload = {
        "decided_at": decided_at,
        "evaluation_id": evaluation.get("evaluation_id") or "",
        "execution_id": evaluation.get("execution_id") or execution.get("execution_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "subject_fingerprint": evaluation.get("subject_fingerprint") or execution.get("fingerprint") or "",
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"promotion_decision_{digest[:32]}"


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    if _contains_registry_secret(payload):
        return True
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer ", "SECRET_CANARY")
    return any(item in rendered for item in forbidden)


def _marker_present(payload: dict[str, Any], markers: tuple[str, ...]) -> bool:
    rendered = json.dumps(payload, sort_keys=True).lower()
    return any(marker.lower() in rendered for marker in markers)


def _assert_decision_safe(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    if _contains_forbidden_data(payload) or any(item in rendered for item in UNSAFE_NEXT_ACTION_MARKERS):
        raise PlaybookValidationError("promotion_decision.unsafe_payload", "Promotion decision contains unsafe data.")
    actions = set(payload.get("eligible_next_actions") or ())
    if not actions <= set(SAFE_NEXT_ACTIONS):
        raise PlaybookValidationError("promotion_decision.unsafe_action", "Promotion decision contains unsafe next action.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))

