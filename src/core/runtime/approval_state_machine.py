from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .approval_request_draft import ApprovalRequestDraft, SAFE_REQUESTED_ACTION_KINDS
from .events import utc_now_iso
from .errors import PlaybookValidationError
from .playbook_registry import _contains_registry_secret
from .promotion_gate import UNSAFE_NEXT_ACTION_MARKERS

APPROVAL_REQUEST_SCHEMA_VERSION = "approval-request.v1"
APPROVAL_STATE_MACHINE_VERSION = "local-approval-state-machine.v1"

APPROVAL_STATUSES = ("approved", "blocked", "cancelled", "expired", "pending", "rejected")
TERMINAL_APPROVAL_STATUSES = {"approved", "blocked", "cancelled", "expired", "rejected"}
APPROVAL_DECISIONS = ("approve", "cancel", "expire", "reject")


@dataclass(frozen=True)
class ApprovalRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = True
    execution_started: bool = False
    production_mutation_used: bool = False


@dataclass(frozen=True)
class ApprovalReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalDecision:
    decision: str
    reviewer_id: str
    reason: str
    decided_at: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalAuditEvent:
    event_id: str
    approval_id: str
    event_type: str
    actor: str
    reason_code: str
    timestamp: str
    provenance: dict[str, Any]
    redaction: ApprovalRedaction

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    draft_id: str
    packet_id: str
    requested_action: str
    requested_action_kind: str
    reviewer_role: str
    scope: dict[str, str]
    status: str
    reason_codes: tuple[ApprovalReason, ...]
    safety_summary: dict[str, Any]
    required_reviews: tuple[str, ...]
    decision: ApprovalDecision | None
    decided_by: str
    decided_at: str
    expires_at: str | None
    audit_events: tuple[ApprovalAuditEvent, ...]
    provenance: dict[str, Any]
    redaction: ApprovalRedaction
    created_at: str
    updated_at: str
    schema_version: str = APPROVAL_REQUEST_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ApprovalTransitionResult:
    approval: ApprovalRequest
    changed: bool
    status: str
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class ApprovalStore:
    approvals: dict[str, ApprovalRequest] = field(default_factory=dict)
    clock: Any = utc_now_iso

    def create_from_draft(self, draft: ApprovalRequestDraft | dict[str, Any], actor: str | None = None) -> ApprovalRequest:
        payload = _payload(draft)
        created_at = self.clock()
        reasons = _draft_reasons(payload)
        status = "pending" if not reasons and payload.get("status") == "draft" else "blocked"
        approval_id = _approval_id(payload, created_at)
        audit = _audit_event(
            approval_id=approval_id,
            event_type="created",
            actor=_safe_text(actor or ""),
            reason_code="created" if status == "pending" else "blocked",
            timestamp=created_at,
            index=0,
        )
        approval = ApprovalRequest(
            approval_id=approval_id,
            draft_id=str(payload.get("draft_id") or ""),
            packet_id=str(payload.get("packet_id") or ""),
            requested_action=str(payload.get("requested_action") or ""),
            requested_action_kind=str(payload.get("requested_action_kind") or ""),
            reviewer_role=str(payload.get("reviewer_role") or ""),
            scope=dict(sorted((payload.get("scope") or {}).items())),
            status=status,
            reason_codes=tuple(sorted(reasons, key=lambda item: (item.severity, item.subject_ref, item.reason_code))),
            safety_summary=_safe_summary(payload.get("safety_summary") or {}),
            required_reviews=tuple(sorted(str(item) for item in payload.get("required_reviews") or () if str(item))),
            decision=None,
            decided_by="",
            decided_at="",
            expires_at=payload.get("expires_at"),
            audit_events=(audit,),
            provenance={
                "state_machine_version": APPROVAL_STATE_MACHINE_VERSION,
                "draft_ref": {"id": str(payload.get("draft_id") or ""), "schema_version": str(payload.get("schema_version") or "")},
            },
            redaction=ApprovalRedaction(),
            created_at=created_at,
            updated_at=created_at,
        )
        _assert_approval_safe(approval.to_dict())
        self.approvals[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.approvals.get(approval_id)

    def list(
        self,
        *,
        status: str | None = None,
        reviewer_role: str | None = None,
        requested_action_kind: str | None = None,
    ) -> tuple[ApprovalRequest, ...]:
        records = self.approvals.values()
        if status is not None:
            records = [item for item in records if item.status == status]
        if reviewer_role is not None:
            records = [item for item in records if item.reviewer_role == reviewer_role]
        if requested_action_kind is not None:
            records = [item for item in records if item.requested_action_kind == requested_action_kind]
        return tuple(sorted(records, key=lambda item: (item.created_at, item.approval_id)))

    def approve(self, approval_id: str, reviewer_id: str, reason: str | None = None) -> ApprovalTransitionResult:
        return self._decide(approval_id, decision="approve", actor=_safe_text(reviewer_id), reason=_safe_text(reason or ""))

    def reject(self, approval_id: str, reviewer_id: str, reason: str | None = None) -> ApprovalTransitionResult:
        return self._decide(approval_id, decision="reject", actor=_safe_text(reviewer_id), reason=_safe_text(reason or ""))

    def cancel(self, approval_id: str, actor: str | None = None, reason: str | None = None) -> ApprovalTransitionResult:
        return self._decide(approval_id, decision="cancel", actor=_safe_text(actor or ""), reason=_safe_text(reason or ""))

    def expire(self, approval_id: str, now: str | None = None) -> ApprovalTransitionResult:
        current = self.approvals[approval_id]
        timestamp = now or self.clock()
        if current.status != "pending":
            return self._invalid(current, "invalid_transition_attempted", actor="", timestamp=timestamp)
        if not current.expires_at or _parse_time(timestamp) < _parse_time(current.expires_at):
            return self._invalid(current, "not_expired", actor="", timestamp=timestamp)
        return self._decide(approval_id, decision="expire", actor="", reason="expired", timestamp=timestamp)

    def audit_events(self, approval_id: str | None = None) -> tuple[ApprovalAuditEvent, ...]:
        if approval_id is not None:
            approval = self.approvals.get(approval_id)
            return tuple(approval.audit_events if approval else ())
        events = [event for approval in self.approvals.values() for event in approval.audit_events]
        return tuple(sorted(events, key=lambda item: (item.timestamp, item.approval_id, item.event_id)))

    def _decide(
        self,
        approval_id: str,
        *,
        decision: str,
        actor: str,
        reason: str,
        timestamp: str | None = None,
    ) -> ApprovalTransitionResult:
        current = self.approvals[approval_id]
        decided_at = timestamp or self.clock()
        if current.status != "pending":
            return self._invalid(current, "invalid_transition_attempted", actor=actor, timestamp=decided_at)
        status = {"approve": "approved", "cancel": "cancelled", "expire": "expired", "reject": "rejected"}[decision]
        audit = _audit_event(
            approval_id=approval_id,
            event_type=status,
            actor=actor,
            reason_code=status,
            timestamp=decided_at,
            index=len(current.audit_events),
        )
        updated = replace(
            current,
            status=status,
            decision=ApprovalDecision(
                decision=decision,
                reviewer_id=actor,
                reason=reason,
                decided_at=decided_at,
                provenance={"state_machine_version": APPROVAL_STATE_MACHINE_VERSION},
            ),
            decided_by=actor,
            decided_at=decided_at,
            audit_events=(*current.audit_events, audit),
            updated_at=decided_at,
        )
        _assert_approval_safe(updated.to_dict())
        self.approvals[approval_id] = updated
        return ApprovalTransitionResult(approval=updated, changed=True, status=status, reason_code=status)

    def _invalid(
        self,
        current: ApprovalRequest,
        reason_code: str,
        *,
        actor: str,
        timestamp: str,
    ) -> ApprovalTransitionResult:
        audit = _audit_event(
            approval_id=current.approval_id,
            event_type="invalid_transition_attempted",
            actor=actor,
            reason_code=reason_code,
            timestamp=timestamp,
            index=len(current.audit_events),
        )
        updated = replace(current, audit_events=(*current.audit_events, audit))
        _assert_approval_safe(updated.to_dict())
        self.approvals[current.approval_id] = updated
        return ApprovalTransitionResult(approval=updated, changed=False, status=current.status, reason_code=reason_code)


def _draft_reasons(payload: dict[str, Any]) -> list[ApprovalReason]:
    reasons: list[ApprovalReason] = []
    if payload.get("status") != "draft":
        reasons.append(_error("draft_not_requestable", "draft.status"))
    action_kind = str(payload.get("requested_action_kind") or "")
    action_text = f"{payload.get('requested_action') or ''} {action_kind}"
    if action_kind not in SAFE_REQUESTED_ACTION_KINDS:
        reasons.append(_error("unsafe_requested_action_kind", "draft.requested_action_kind"))
    if any(marker in action_text for marker in UNSAFE_NEXT_ACTION_MARKERS):
        reasons.append(_error("unsafe_requested_action_kind", "draft.requested_action_kind"))
    redaction = payload.get("redaction") or {}
    if any(redaction.get(key) is not False for key in ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included")):
        reasons.append(_error("unsafe_redaction", "draft.redaction"))
    return reasons


def _audit_event(
    *,
    approval_id: str,
    event_type: str,
    actor: str,
    reason_code: str,
    timestamp: str,
    index: int,
) -> ApprovalAuditEvent:
    event_id = _event_id(approval_id, event_type, timestamp, index)
    return ApprovalAuditEvent(
        event_id=event_id,
        approval_id=approval_id,
        event_type=event_type,
        actor=actor,
        reason_code=reason_code,
        timestamp=timestamp,
        provenance={"state_machine_version": APPROVAL_STATE_MACHINE_VERSION},
        redaction=ApprovalRedaction(),
    )


def _approval_id(payload: dict[str, Any], created_at: str) -> str:
    seed = {
        "created_at": created_at,
        "draft_id": payload.get("draft_id") or "",
        "packet_id": payload.get("packet_id") or "",
        "requested_action_kind": payload.get("requested_action_kind") or "",
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"approval_request_{digest[:32]}"


def _event_id(approval_id: str, event_type: str, timestamp: str, index: int) -> str:
    seed = {"approval_id": approval_id, "event_type": event_type, "index": index, "timestamp": timestamp}
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"approval_audit_{digest[:32]}"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_summary(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "decision_status",
        "evaluation_status",
        "execution_read_only",
        "execution_sandbox",
        "packet_status",
        "plan_executable",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "safe_next_action_source",
        "secrets_included",
    }
    return {key: _json_safe(value[key]) for key in sorted(value) if key in allowed}


def _safe_text(value: str) -> str:
    rendered = str(value or "")
    if _contains_registry_secret({"value": rendered}):
        return ""
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    if any(item in rendered for item in forbidden):
        return ""
    return rendered


def _payload(value: ApprovalRequestDraft | dict[str, Any]) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ApprovalReason:
    return ApprovalReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _assert_approval_safe(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer", "SECRET_CANARY")
    action_text = f"{payload.get('requested_action') or ''} {payload.get('requested_action_kind') or ''}"
    if _contains_registry_secret(payload) or any(item in rendered for item in forbidden) or any(
        marker in action_text for marker in UNSAFE_NEXT_ACTION_MARKERS
    ):
        raise PlaybookValidationError("approval_request.unsafe_payload", "Approval request contains unsafe data.")
    if payload.get("status") not in APPROVAL_STATUSES:
        raise PlaybookValidationError("approval_request.invalid_status", "Approval request status is invalid.")
    redaction = payload.get("redaction") or {}
    if redaction.get("execution_started") is not False or redaction.get("production_mutation_used") is not False:
        raise PlaybookValidationError("approval_request.unsafe_side_effect", "Approval request recorded forbidden effects.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
