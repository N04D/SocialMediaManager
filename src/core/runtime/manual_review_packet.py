from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .playbook_registry import _contains_registry_secret
from .promotion_gate import SAFE_NEXT_ACTIONS

MANUAL_REVIEW_PACKET_SCHEMA_VERSION = "manual-review-packet.v1"
MANUAL_REVIEW_PACKET_BUILDER_VERSION = "manual-review-packet-builder.v1"

ALLOWED_PACKET_STATUSES = {"blocked_from_review", "informational", "ready_for_review"}
SAFE_REVIEW_ACTIONS = set(SAFE_NEXT_ACTIONS)


@dataclass(frozen=True)
class ReviewPacketPolicy:
    policy_id: str = "manual-review-packet-default"
    version: str = "1.0.0"
    include_step_output: bool = False
    include_check_details: bool = True
    include_provenance_refs: bool = True
    allow_blocked_packets: bool = True
    require_decision: bool = True
    require_evaluation: bool = False
    require_execution: bool = False
    require_plan: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ReviewReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class DecisionSummary:
    decision_id: str
    status: str
    reason_codes: tuple[str, ...]
    severities: tuple[str, ...]
    safe_next_actions: tuple[str, ...]
    required_reviews: tuple[str, ...]
    policy_id: str
    policy_version: str


@dataclass(frozen=True)
class EvaluationSummary:
    evaluation_id: str
    status: str
    check_counts: dict[str, int]
    warning_reason_codes: tuple[str, ...]
    failure_reason_codes: tuple[str, ...]
    policy_version: str
    subject_fingerprint: str


@dataclass(frozen=True)
class ExecutionSummary:
    execution_id: str
    playbook_id: str
    playbook_version: str
    sandbox: bool
    read_only: bool
    status: str
    step_counts_by_status: dict[str, int]
    blocker_reason_codes: tuple[str, ...]
    redaction_flags: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class PlanSummary:
    plan_id: str
    playbook_id: str
    playbook_version: str
    executable: bool
    step_count: int
    blocked_reasons: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    raw_access_required: bool
    mutation_required: bool


@dataclass(frozen=True)
class PacketRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    full_step_outputs_included: bool = False


@dataclass(frozen=True)
class ManualReviewPacket:
    packet_id: str
    subject_execution_id: str
    subject_evaluation_id: str
    subject_decision_id: str
    status: str
    review_reason: tuple[ReviewReason, ...]
    decision_summary: DecisionSummary | None
    evaluation_summary: EvaluationSummary | None
    execution_summary: ExecutionSummary | None
    plan_summary: PlanSummary | None
    safe_next_actions: tuple[str, ...]
    required_reviews: tuple[str, ...]
    provenance: dict[str, Any]
    redaction: PacketRedaction
    generated_at: str
    schema_version: str = MANUAL_REVIEW_PACKET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ManualReviewPacketBuilder:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def build(
        self,
        decision: Any | None,
        *,
        evaluation: Any | None = None,
        execution_record: Any | None = None,
        plan: Any | None = None,
        policy: ReviewPacketPolicy | None = None,
    ) -> ManualReviewPacket:
        selected_policy = policy or ReviewPacketPolicy()
        generated_at = self.clock()
        decision_payload = _payload(decision)
        evaluation_payload = _payload(evaluation)
        execution_payload = _payload(execution_record)
        plan_payload = _payload(plan)
        reasons = []
        reasons.extend(_presence_reasons(decision_payload, evaluation_payload, execution_payload, plan_payload, selected_policy))
        decision_summary = _decision_summary(decision_payload, reasons)
        evaluation_summary = _evaluation_summary(evaluation_payload, selected_policy, reasons)
        execution_summary = _execution_summary(execution_payload, reasons)
        plan_summary = _plan_summary(plan_payload, reasons)
        actions = _safe_actions(decision_payload, reasons)
        status = _packet_status(decision_payload, reasons, selected_policy)
        packet = ManualReviewPacket(
            packet_id=_packet_id(decision_payload, evaluation_payload, execution_payload, plan_payload, selected_policy, generated_at),
            subject_execution_id=str(
                decision_payload.get("subject_execution_id")
                or evaluation_payload.get("execution_id")
                or execution_payload.get("execution_id")
                or ""
            ),
            subject_evaluation_id=str(decision_payload.get("subject_evaluation_id") or evaluation_payload.get("evaluation_id") or ""),
            subject_decision_id=str(decision_payload.get("decision_id") or ""),
            status=status,
            review_reason=tuple(sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code))),
            decision_summary=decision_summary,
            evaluation_summary=evaluation_summary,
            execution_summary=execution_summary,
            plan_summary=plan_summary,
            safe_next_actions=tuple(sorted(actions)),
            required_reviews=tuple(sorted(str(item) for item in decision_payload.get("required_reviews") or () if str(item))),
            provenance=_provenance(decision_payload, evaluation_payload, execution_payload, plan_payload, selected_policy),
            redaction=PacketRedaction(full_step_outputs_included=bool(selected_policy.include_step_output)),
            generated_at=generated_at,
        )
        _assert_packet_safe(packet.to_dict())
        return packet

    def summarize(self, packet: ManualReviewPacket) -> dict[str, Any]:
        return {
            "packet_id": packet.packet_id,
            "status": packet.status,
            "subject_decision_id": packet.subject_decision_id,
            "subject_execution_id": packet.subject_execution_id,
            "reason_codes": [reason.reason_code for reason in packet.review_reason],
            "safe_next_actions": list(packet.safe_next_actions),
            "required_reviews": list(packet.required_reviews),
        }


def _presence_reasons(
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    plan: dict[str, Any],
    policy: ReviewPacketPolicy,
) -> list[ReviewReason]:
    reasons: list[ReviewReason] = []
    if not decision:
        reasons.append(_error("missing_decision" if policy.require_decision else "missing_decision_optional", "decision"))
    if not evaluation:
        reasons.append((_error if policy.require_evaluation else _warning)("missing_evaluation", "evaluation"))
    if not execution:
        reasons.append((_error if policy.require_execution else _warning)("missing_execution", "execution"))
    if not plan:
        reasons.append((_error if policy.require_plan else _warning)("missing_plan", "plan"))
    return reasons


def _decision_summary(decision: dict[str, Any], reasons: list[ReviewReason]) -> DecisionSummary | None:
    if not decision:
        return None
    status = str(decision.get("status") or "")
    if status == "needs_review":
        reasons.append(_warning("decision_needs_review", "decision"))
    elif status == "blocked":
        reasons.append(_warning("decision_blocked", "decision"))
    elif status == "eligible":
        reasons.append(_info("decision_eligible", "decision"))
    else:
        reasons.append(_error("unsupported_decision_status", "decision", {"status": status}))
    decision_reasons = tuple(_reason_code(item) for item in decision.get("reasons") or ())
    severities = tuple(sorted({_severity(item) for item in decision.get("reasons") or () if _severity(item)}))
    return DecisionSummary(
        decision_id=str(decision.get("decision_id") or ""),
        status=status,
        reason_codes=tuple(sorted(item for item in decision_reasons if item)),
        severities=severities,
        safe_next_actions=tuple(sorted(str(item) for item in decision.get("eligible_next_actions") or () if str(item) in SAFE_REVIEW_ACTIONS)),
        required_reviews=tuple(sorted(str(item) for item in decision.get("required_reviews") or () if str(item))),
        policy_id=str(decision.get("policy_id") or ""),
        policy_version=str(decision.get("policy_version") or ""),
    )


def _evaluation_summary(
    evaluation: dict[str, Any],
    policy: ReviewPacketPolicy,
    reasons: list[ReviewReason],
) -> EvaluationSummary | None:
    if not evaluation:
        return None
    status = str(evaluation.get("status") or "")
    if status == "warning":
        reasons.append(_warning("evaluation_warning", "evaluation"))
    elif status == "failed":
        reasons.append(_error("evaluation_failed", "evaluation"))
    counts: dict[str, int] = {}
    for check in evaluation.get("checks") or ():
        check_status = str(check.get("status") or "")
        counts[check_status] = counts.get(check_status, 0) + 1
    if not policy.include_check_details:
        counts = dict(sorted(counts.items()))
    return EvaluationSummary(
        evaluation_id=str(evaluation.get("evaluation_id") or ""),
        status=status,
        check_counts=dict(sorted(counts.items())),
        warning_reason_codes=tuple(sorted(str(item) for item in evaluation.get("warnings") or () if str(item))),
        failure_reason_codes=tuple(sorted(str(item) for item in evaluation.get("failures") or () if str(item))),
        policy_version=str(evaluation.get("policy_version") or ""),
        subject_fingerprint=str(evaluation.get("subject_fingerprint") or ""),
    )


def _execution_summary(execution: dict[str, Any], reasons: list[ReviewReason]) -> ExecutionSummary | None:
    if not execution:
        return None
    redaction = dict(execution.get("redaction") or {})
    if any(redaction.get(key) is True for key in ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included")):
        reasons.append(_error("unsafe_redaction", "execution.redaction"))
    counts: dict[str, int] = {}
    blockers = set(str(item) for item in execution.get("blocked_reasons") or () if str(item))
    for step in execution.get("step_results") or ():
        status = str(step.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
        blockers.update(str(item) for item in step.get("blocked_reasons") or () if str(item))
    return ExecutionSummary(
        execution_id=str(execution.get("execution_id") or ""),
        playbook_id=str(execution.get("playbook_id") or ""),
        playbook_version=str(execution.get("playbook_version") or ""),
        sandbox=bool(execution.get("sandbox")),
        read_only=bool(execution.get("read_only")),
        status=str(execution.get("status") or ""),
        step_counts_by_status=dict(sorted(counts.items())),
        blocker_reason_codes=tuple(sorted(blockers)),
        redaction_flags=_safe_redaction_flags(redaction),
        fingerprint=str(execution.get("fingerprint") or ""),
    )


def _plan_summary(plan: dict[str, Any], reasons: list[ReviewReason]) -> PlanSummary | None:
    if not plan:
        return None
    return PlanSummary(
        plan_id=str(plan.get("plan_id") or ""),
        playbook_id=str(plan.get("playbook_id") or ""),
        playbook_version=str(plan.get("playbook_version") or ""),
        executable=bool(plan.get("executable")),
        step_count=len(plan.get("step_plans") or ()),
        blocked_reasons=tuple(sorted(str(item) for item in plan.get("blocked_reasons") or () if str(item))),
        required_capabilities=tuple(sorted(str(item) for item in plan.get("required_capabilities") or () if str(item))),
        raw_access_required=bool(plan.get("raw_access_required")),
        mutation_required=bool(plan.get("mutation_required")),
    )


def _packet_status(decision: dict[str, Any], reasons: list[ReviewReason], policy: ReviewPacketPolicy) -> str:
    if any(reason.severity == "error" for reason in reasons):
        return "blocked_from_review"
    decision_status = str(decision.get("status") or "")
    if decision_status == "needs_review":
        return "ready_for_review"
    if decision_status in {"eligible", "blocked"}:
        return "informational" if policy.allow_blocked_packets else "blocked_from_review"
    return "blocked_from_review"


def _safe_actions(decision: dict[str, Any], reasons: list[ReviewReason]) -> set[str]:
    safe = set()
    for action in decision.get("eligible_next_actions") or ():
        rendered = str(action)
        if rendered in SAFE_REVIEW_ACTIONS:
            safe.add(rendered)
        elif rendered:
            reasons.append(_warning("unsafe_next_action_omitted", f"action:{rendered}"))
    return safe


def _provenance(
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    plan: dict[str, Any],
    policy: ReviewPacketPolicy,
) -> dict[str, Any]:
    return {
        "builder_version": MANUAL_REVIEW_PACKET_BUILDER_VERSION,
        "policy": policy.to_dict(),
        "decision_ref": _ref(decision, "decision_id", "schema_version"),
        "evaluation_ref": _ref(evaluation, "evaluation_id", "schema_version"),
        "execution_ref": _ref(execution, "execution_id", "schema_version"),
        "plan_ref": _ref(plan, "plan_id", "schema_version"),
    }


def _ref(payload: dict[str, Any], id_key: str, schema_key: str) -> dict[str, str]:
    if not payload:
        return {}
    return {"id": str(payload.get(id_key) or ""), "schema_version": str(payload.get(schema_key) or "")}


def _safe_redaction_flags(redaction: dict[str, Any]) -> dict[str, Any]:
    keys = ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included")
    return {key: bool(redaction.get(key)) for key in keys}


def _packet_id(
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    plan: dict[str, Any],
    policy: ReviewPacketPolicy,
    generated_at: str,
) -> str:
    payload = {
        "decision_id": decision.get("decision_id") or "",
        "evaluation_id": evaluation.get("evaluation_id") or "",
        "execution_id": execution.get("execution_id") or "",
        "generated_at": generated_at,
        "plan_id": plan.get("plan_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"manual_review_packet_{digest[:32]}"


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _reason_code(reason: Any) -> str:
    if isinstance(reason, dict):
        return str(reason.get("reason_code") or "")
    return str(getattr(reason, "reason_code", "") or "")


def _severity(reason: Any) -> str:
    if isinstance(reason, dict):
        return str(reason.get("severity") or "")
    return str(getattr(reason, "severity", "") or "")


def _info(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ReviewReason:
    return ReviewReason(reason_code=reason_code, severity="info", subject_ref=subject_ref, details=details or {})


def _warning(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ReviewReason:
    return ReviewReason(reason_code=reason_code, severity="warning", subject_ref=subject_ref, details=details or {})


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ReviewReason:
    return ReviewReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _assert_packet_safe(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    if _contains_registry_secret(payload) or any(item in rendered for item in forbidden):
        raise PlaybookValidationError("manual_review_packet.unsafe_payload", "Manual review packet contains unsafe data.")
    actions = set(payload.get("safe_next_actions") or ())
    if not actions <= SAFE_REVIEW_ACTIONS:
        raise PlaybookValidationError("manual_review_packet.unsafe_action", "Manual review packet contains unsafe action.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))

