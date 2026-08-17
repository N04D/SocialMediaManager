from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .manual_review_packet import ManualReviewPacket
from .playbook_registry import _contains_registry_secret
from .promotion_gate import SAFE_NEXT_ACTIONS, UNSAFE_NEXT_ACTION_MARKERS

APPROVAL_REQUEST_DRAFT_SCHEMA_VERSION = "approval-request-draft.v1"
APPROVAL_REQUEST_DRAFT_BUILDER_VERSION = "approval-request-draft-builder.v1"

SAFE_ACTION_TO_KIND = {
    "allow_manual_review": "manual_review",
    "allow_prepare_approval_request": "prepare_approval_request",
    "allow_read_only_agent_consumption": "read_only_agent_consumption",
    "allow_sandbox_replay": "sandbox_replay",
}
SAFE_REQUESTED_ACTION_KINDS = tuple(sorted(set(SAFE_ACTION_TO_KIND.values())))
ALLOWED_DRAFT_STATUSES = {"blocked", "draft", "not_requestable"}


@dataclass(frozen=True)
class ApprovalRequestDraftPolicy:
    policy_id: str = "approval-request-draft-default"
    version: str = "1.0.0"
    allowed_action_kinds: tuple[str, ...] = SAFE_REQUESTED_ACTION_KINDS
    default_reviewer_role: str = "human_reviewer"
    require_ready_for_review: bool = True
    allow_informational: bool = False
    allow_blocked: bool = False
    default_expiration_hours: int | None = None
    require_safe_redaction: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalRequestReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalRequestRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False


@dataclass(frozen=True)
class ApprovalRequestDraft:
    draft_id: str
    packet_id: str
    subject_execution_id: str
    subject_decision_id: str
    requested_action: str
    requested_action_kind: str
    reviewer_role: str
    scope: dict[str, str]
    status: str
    reason_codes: tuple[ApprovalRequestReason, ...]
    safety_summary: dict[str, Any]
    required_reviews: tuple[str, ...]
    expires_at: str | None
    provenance: dict[str, Any]
    redaction: ApprovalRequestRedaction
    created_at: str
    schema_version: str = APPROVAL_REQUEST_DRAFT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ApprovalRequestDraftBuilder:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def build(
        self,
        packet: ManualReviewPacket | dict[str, Any],
        requested_action: str,
        *,
        policy: ApprovalRequestDraftPolicy | None = None,
    ) -> ApprovalRequestDraft:
        selected_policy = policy or ApprovalRequestDraftPolicy()
        created_at = self.clock()
        payload = _payload(packet)
        reasons: list[ApprovalRequestReason] = []
        safe_actions = _packet_safe_actions(payload, reasons)
        requested_action_kind, source_action = _requested_action_kind(requested_action, safe_actions, reasons)
        reasons.extend(_policy_reasons(payload, requested_action_kind, source_action, safe_actions, selected_policy))
        status = _draft_status(payload, reasons, source_action, requested_action_kind, selected_policy)
        expires_at = _expires_at(created_at, selected_policy.default_expiration_hours) if status == "draft" else None
        summary = _safety_summary(payload, source_action)
        draft = ApprovalRequestDraft(
            draft_id=_draft_id(payload, requested_action_kind, source_action, selected_policy, created_at),
            packet_id=str(payload.get("packet_id") or ""),
            subject_execution_id=str(payload.get("subject_execution_id") or ""),
            subject_decision_id=str(payload.get("subject_decision_id") or ""),
            requested_action=source_action,
            requested_action_kind=requested_action_kind,
            reviewer_role=str(selected_policy.default_reviewer_role),
            scope=_scope(payload, requested_action_kind),
            status=status,
            reason_codes=tuple(sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code))),
            safety_summary=summary,
            required_reviews=tuple(sorted(str(item) for item in payload.get("required_reviews") or () if str(item))),
            expires_at=expires_at,
            provenance=_provenance(payload, selected_policy),
            redaction=ApprovalRequestRedaction(),
            created_at=created_at,
        )
        _assert_draft_safe(draft.to_dict())
        return draft

    def available_actions(
        self,
        packet: ManualReviewPacket | dict[str, Any],
        *,
        policy: ApprovalRequestDraftPolicy | None = None,
    ) -> tuple[str, ...]:
        selected_policy = policy or ApprovalRequestDraftPolicy()
        payload = _payload(packet)
        reasons: list[ApprovalRequestReason] = []
        actions = _packet_safe_actions(payload, reasons)
        allowed = set(selected_policy.allowed_action_kinds)
        return tuple(sorted(kind for action, kind in SAFE_ACTION_TO_KIND.items() if action in actions and kind in allowed))

    def summarize(self, draft: ApprovalRequestDraft) -> dict[str, Any]:
        return {
            "draft_id": draft.draft_id,
            "packet_id": draft.packet_id,
            "status": draft.status,
            "requested_action_kind": draft.requested_action_kind,
            "reviewer_role": draft.reviewer_role,
            "reason_codes": [reason.reason_code for reason in draft.reason_codes],
            "required_reviews": list(draft.required_reviews),
            "expires_at": draft.expires_at,
        }


def _policy_reasons(
    packet: dict[str, Any],
    action_kind: str,
    source_action: str,
    safe_actions: tuple[str, ...],
    policy: ApprovalRequestDraftPolicy,
) -> list[ApprovalRequestReason]:
    reasons: list[ApprovalRequestReason] = []
    packet_status = str(packet.get("status") or "")
    if policy.require_ready_for_review and packet_status != "ready_for_review":
        if packet_status == "informational" and policy.allow_informational:
            reasons.append(_info("informational_packet_allowed", "packet.status"))
        elif packet_status == "blocked_from_review" and policy.allow_blocked:
            reasons.append(_warning("blocked_packet_allowed", "packet.status"))
        elif packet_status == "blocked_from_review":
            reasons.append(_error("packet_blocked_from_review", "packet.status"))
        else:
            reasons.append(_warning("packet_not_ready_for_review", "packet.status"))
    if source_action and source_action not in safe_actions:
        reasons.append(_warning("action_not_allowed_by_packet", "requested_action"))
    if not source_action:
        reasons.append(_warning("action_not_allowed_by_packet", "requested_action"))
    if action_kind not in policy.allowed_action_kinds:
        reasons.append(_warning("action_kind_not_allowed", "requested_action_kind"))
    if action_kind not in SAFE_REQUESTED_ACTION_KINDS:
        reasons.append(_warning("unsupported_requested_action", "requested_action_kind"))
    if policy.require_safe_redaction and not _redaction_safe(packet):
        reasons.append(_error("unsafe_redaction", "packet.redaction"))
    if policy.require_safe_redaction and any(
        str(reason.get("reason_code") or "") == "unsafe_redaction" for reason in packet.get("review_reason") or ()
    ):
        reasons.append(_error("unsafe_redaction", "packet.review_reason"))
    return reasons


def _draft_status(
    packet: dict[str, Any],
    reasons: list[ApprovalRequestReason],
    source_action: str,
    action_kind: str,
    policy: ApprovalRequestDraftPolicy,
) -> str:
    if any(reason.severity == "error" for reason in reasons):
        return "blocked"
    packet_status = str(packet.get("status") or "")
    if policy.require_ready_for_review and packet_status != "ready_for_review" and not (
        packet_status == "informational" and policy.allow_informational
    ) and not (packet_status == "blocked_from_review" and policy.allow_blocked):
        return "not_requestable"
    if not source_action or action_kind not in policy.allowed_action_kinds or action_kind not in SAFE_REQUESTED_ACTION_KINDS:
        return "not_requestable"
    return "draft"


def _packet_safe_actions(packet: dict[str, Any], reasons: list[ApprovalRequestReason]) -> tuple[str, ...]:
    actions = []
    for action in packet.get("safe_next_actions") or ():
        rendered = str(action)
        if rendered in SAFE_NEXT_ACTIONS:
            actions.append(rendered)
        elif rendered:
            reasons.append(_warning("unsafe_action_omitted", "packet.safe_next_actions"))
    return tuple(sorted(set(actions)))


def _requested_action_kind(
    requested_action: str,
    safe_actions: tuple[str, ...],
    reasons: list[ApprovalRequestReason],
) -> tuple[str, str]:
    rendered = str(requested_action or "")
    if rendered in SAFE_ACTION_TO_KIND:
        return SAFE_ACTION_TO_KIND[rendered], rendered if rendered in safe_actions else ""
    if rendered in SAFE_REQUESTED_ACTION_KINDS:
        for action, kind in sorted(SAFE_ACTION_TO_KIND.items()):
            if kind == rendered and action in safe_actions:
                return kind, action
        return rendered, ""
    if rendered:
        reasons.append(_warning("unsafe_action_omitted", "requested_action"))
    return "unsupported", ""


def _safety_summary(packet: dict[str, Any], source_action: str) -> dict[str, Any]:
    decision = packet.get("decision_summary") or {}
    evaluation = packet.get("evaluation_summary") or {}
    execution = packet.get("execution_summary") or {}
    plan = packet.get("plan_summary") or {}
    redaction = packet.get("redaction") or {}
    return _json_safe(
        {
            "decision_status": str(decision.get("status") or ""),
            "evaluation_status": str(evaluation.get("status") or ""),
            "execution_read_only": bool(execution.get("read_only")) if execution else None,
            "execution_sandbox": bool(execution.get("sandbox")) if execution else None,
            "packet_status": str(packet.get("status") or ""),
            "plan_executable": bool(plan.get("executable")) if plan else None,
            "raw_metrics_included": bool(redaction.get("raw_metrics_included")),
            "raw_transcript_included": bool(redaction.get("raw_transcript_included")),
            "secrets_included": bool(redaction.get("secrets_included")),
            "provider_headers_included": bool(redaction.get("provider_headers_included")),
            "safe_next_action_source": source_action,
        }
    )


def _scope(packet: dict[str, Any], requested_action_kind: str) -> dict[str, str]:
    execution = packet.get("execution_summary") or {}
    plan = packet.get("plan_summary") or {}
    return dict(
        sorted(
            {
                "decision_id": str(packet.get("subject_decision_id") or ""),
                "execution_id": str(packet.get("subject_execution_id") or ""),
                "packet_id": str(packet.get("packet_id") or ""),
                "playbook_id": str(plan.get("playbook_id") or execution.get("playbook_id") or ""),
                "playbook_version": str(plan.get("playbook_version") or execution.get("playbook_version") or ""),
                "requested_action_kind": requested_action_kind,
            }.items()
        )
    )


def _provenance(packet: dict[str, Any], policy: ApprovalRequestDraftPolicy) -> dict[str, Any]:
    return {
        "builder_version": APPROVAL_REQUEST_DRAFT_BUILDER_VERSION,
        "packet_ref": {"id": str(packet.get("packet_id") or ""), "schema_version": str(packet.get("schema_version") or "")},
        "policy": policy.to_dict(),
    }


def _expires_at(created_at: str, expiration_hours: int | None) -> str | None:
    if expiration_hours is None:
        return None
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(hours=expiration_hours)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _redaction_safe(packet: dict[str, Any]) -> bool:
    redaction = packet.get("redaction") or {}
    keys = ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included")
    return all(redaction.get(key) is False for key in keys)


def _draft_id(
    packet: dict[str, Any],
    requested_action_kind: str,
    source_action: str,
    policy: ApprovalRequestDraftPolicy,
    created_at: str,
) -> str:
    payload = {
        "created_at": created_at,
        "packet_id": packet.get("packet_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "requested_action": source_action,
        "requested_action_kind": requested_action_kind,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"approval_request_draft_{digest[:32]}"


def _payload(value: ManualReviewPacket | dict[str, Any]) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _info(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ApprovalRequestReason:
    return ApprovalRequestReason(reason_code=reason_code, severity="info", subject_ref=subject_ref, details=details or {})


def _warning(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ApprovalRequestReason:
    return ApprovalRequestReason(reason_code=reason_code, severity="warning", subject_ref=subject_ref, details=details or {})


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ApprovalRequestReason:
    return ApprovalRequestReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _assert_draft_safe(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    action_text = f"{payload.get('requested_action') or ''} {payload.get('requested_action_kind') or ''}"
    if _contains_registry_secret(payload) or any(item in rendered for item in forbidden) or any(
        item in action_text for item in UNSAFE_NEXT_ACTION_MARKERS
    ):
        raise PlaybookValidationError("approval_request_draft.unsafe_payload", "Approval request draft contains unsafe data.")
    if payload.get("status") not in ALLOWED_DRAFT_STATUSES:
        raise PlaybookValidationError("approval_request_draft.invalid_status", "Approval request draft status is invalid.")
    if payload.get("requested_action_kind") not in {*SAFE_REQUESTED_ACTION_KINDS, "unsupported"}:
        raise PlaybookValidationError("approval_request_draft.unsafe_action", "Approval request draft action is unsafe.")
    redaction = payload.get("redaction") or {}
    if redaction.get("approval_state_mutated") is not False:
        raise PlaybookValidationError("approval_request_draft.state_mutated", "Approval request draft mutated approval state.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
