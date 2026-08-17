from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval_request_draft import SAFE_REQUESTED_ACTION_KINDS
from .errors import PlaybookValidationError
from .events import utc_now_iso
from .execution_claim_store import ExecutionClaim
from .playbook_registry import _contains_registry_secret

EXECUTION_ATTEMPT_SCHEMA_VERSION = "execution-attempt.v1"
EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION = "execution-attempt-ledger.v1"

ATTEMPT_MODES = ("no_op", "non_production", "simulation")
ATTEMPT_STATUSES = ("blocked", "cancelled", "completed_noop", "failed_safe", "opened")
TERMINAL_ATTEMPT_STATUSES = {"blocked", "cancelled", "completed_noop", "failed_safe"}


@dataclass(frozen=True)
class ExecutionAttemptRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    production_mutation_used: bool = False
    external_write_used: bool = False
    ai_call_used: bool = False


@dataclass(frozen=True)
class ExecutionAttemptReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionAttemptEvent:
    event_id: str
    attempt_id: str
    preparation_id: str
    claim_id: str
    event_type: str
    reason: str
    timestamp: str
    provenance: dict[str, Any]
    redaction: ExecutionAttemptRedaction
    sequence: int = 0
    schema_version: str = EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionAttemptRecord:
    attempt_id: str
    preparation_id: str
    claim_id: str
    idempotency_key: str
    playbook_id: str
    playbook_version: str
    requested_action_kind: str
    mode: str
    status: str
    started_at: str
    completed_at: str
    result: dict[str, Any]
    blocked_reasons: tuple[ExecutionAttemptReason, ...]
    events: tuple[ExecutionAttemptEvent, ...]
    provenance: dict[str, Any]
    redaction: ExecutionAttemptRedaction
    schema_version: str = EXECUTION_ATTEMPT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionAttemptResult:
    status: str
    attempt: ExecutionAttemptRecord | None
    existing_attempt: ExecutionAttemptRecord | None
    reasons: tuple[ExecutionAttemptReason, ...]

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionAttemptLedger:
    def __init__(self, path: Path | str, *, clock=utc_now_iso):
        self.path = Path(path)
        self.clock = clock

    def open_attempt(
        self,
        claim: ExecutionClaim | dict[str, Any] | None,
        preparation: dict[str, Any] | None,
        *,
        mode: str = "no_op",
        actor: str | None = None,
        now: str | None = None,
    ) -> ExecutionAttemptResult:
        timestamp = now or self.clock()
        claim_payload = _payload(claim)
        preparation_payload = _json_safe(preparation or {})
        safe_mode = str(mode or "")
        state = self._load_state()
        reasons = _open_reasons(claim_payload, preparation_payload, safe_mode, timestamp)
        active = _active_attempt(state, claim_payload.get("claim_id", ""), preparation_payload.get("preparation_id", ""), safe_mode)
        if active is not None:
            reasons.append(_error("active_attempt_exists", "attempt"))

        if reasons:
            attempt = _attempt_from_payload(
                attempt_id=_attempt_id(claim_payload, preparation_payload, safe_mode, timestamp, len(state["attempts"])),
                claim=claim_payload,
                preparation=preparation_payload,
                mode=safe_mode,
                status="blocked",
                timestamp=timestamp,
                completed_at=timestamp,
                result={},
                reasons=tuple(sorted(reasons, key=_reason_key)),
                actor=actor,
            )
            state["attempts"][attempt.attempt_id] = attempt.to_dict()
            event_type = "duplicate_attempt_detected" if active is not None else "attempt_blocked"
            event = _event(
                attempt=attempt,
                event_type=event_type,
                reason=";".join(sorted(reason.reason_code for reason in reasons)),
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            )
            state["audit_events"].append(event.to_dict())
            self._write_state(state)
            return ExecutionAttemptResult(
                status="blocked",
                attempt=attempt,
                existing_attempt=active,
                reasons=tuple(sorted(reasons, key=_reason_key)),
            )

        attempt = _attempt_from_payload(
            attempt_id=_attempt_id(claim_payload, preparation_payload, safe_mode, timestamp, len(state["attempts"])),
            claim=claim_payload,
            preparation=preparation_payload,
            mode=safe_mode,
            status="opened",
            timestamp=timestamp,
            completed_at="",
            result={},
            reasons=(),
            actor=actor,
        )
        event = _event(
            attempt=attempt,
            event_type="attempt_opened",
            reason="attempt_opened",
            timestamp=timestamp,
            sequence=len(state["audit_events"]),
        )
        attempt = _attempt_from_dict({**attempt.to_dict(), "events": [event.to_dict()]})
        state["attempts"][attempt.attempt_id] = attempt.to_dict()
        state["audit_events"].append(event.to_dict())
        self._write_state(state)
        return ExecutionAttemptResult(status="opened", attempt=attempt, existing_attempt=None, reasons=(_info("attempt_opened", "attempt"),))

    def get(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        payload = self._load_state()["attempts"].get(attempt_id)
        return _attempt_from_dict(payload) if payload is not None else None

    def list(
        self,
        *,
        status: str | None = None,
        preparation_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ExecutionAttemptRecord, ...]:
        attempts = [_attempt_from_dict(item) for item in self._load_state()["attempts"].values()]
        if status is not None:
            attempts = [item for item in attempts if item.status == status]
        if preparation_id is not None:
            attempts = [item for item in attempts if item.preparation_id == preparation_id]
        if claim_id is not None:
            attempts = [item for item in attempts if item.claim_id == claim_id]
        return tuple(sorted(attempts, key=lambda item: (item.started_at, item.attempt_id)))

    def complete_noop(self, attempt_id: str, *, result: dict[str, Any] | None = None, now: str | None = None) -> ExecutionAttemptResult:
        safe_result = {
            "ai_call_used": False,
            "completed": True,
            "external_write_used": False,
            "production_mutation_used": False,
            "raw_access_used": False,
            "side_effects": False,
        }
        for key, value in sorted((result or {}).items()):
            if key not in safe_result:
                safe_result[str(key)] = _safe_value(value)
        return self._transition(attempt_id, "completed_noop", reason="attempt_completed_noop", result=safe_result, now=now)

    def fail_safe(self, attempt_id: str, reason: str, *, now: str | None = None) -> ExecutionAttemptResult:
        return self._transition(attempt_id, "failed_safe", reason=reason or "attempt_failed_safe", result={}, now=now)

    def cancel(self, attempt_id: str, reason: str | None = None, *, now: str | None = None) -> ExecutionAttemptResult:
        return self._transition(attempt_id, "cancelled", reason=reason or "attempt_cancelled", result={}, now=now)

    def audit_events(self, *, attempt_id: str | None = None) -> tuple[dict[str, Any], ...]:
        events = self._load_state()["audit_events"]
        if attempt_id is not None:
            events = [item for item in events if item.get("attempt_id") == attempt_id]
        return tuple(
            _json_safe(
                sorted(
                    events,
                    key=lambda item: (
                        int(item.get("sequence") or 0),
                        str(item.get("timestamp") or ""),
                        str(item.get("event_id") or ""),
                    ),
                )
            )
        )

    def _transition(
        self,
        attempt_id: str,
        target_status: str,
        *,
        reason: str,
        result: dict[str, Any],
        now: str | None,
    ) -> ExecutionAttemptResult:
        timestamp = now or self.clock()
        state = self._load_state()
        payload = state["attempts"].get(attempt_id)
        if payload is None:
            return ExecutionAttemptResult(status="blocked", attempt=None, existing_attempt=None, reasons=(_error("attempt_not_found", "attempt_id"),))
        current = _attempt_from_dict(payload)
        if current.status != "opened":
            event = _event(
                attempt=current,
                event_type="invalid_transition_attempted",
                reason="invalid_transition_attempted",
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            )
            state["audit_events"].append(event.to_dict())
            self._write_state(state)
            return ExecutionAttemptResult(
                status=current.status,
                attempt=current,
                existing_attempt=None,
                reasons=(_error("invalid_transition_attempted", "attempt.status", {"status": current.status}),),
            )

        event_type = {
            "cancelled": "attempt_cancelled",
            "completed_noop": "attempt_completed_noop",
            "failed_safe": "attempt_failed_safe",
        }[target_status]
        event = _event(
            attempt=current,
            event_type=event_type,
            reason=reason,
            timestamp=timestamp,
            sequence=len(state["audit_events"]),
        )
        updated = _attempt_from_dict(
            {
                **current.to_dict(),
                "completed_at": timestamp,
                "events": [*current.to_dict().get("events", []), event.to_dict()],
                "result": _json_safe(result),
                "status": target_status,
            }
        )
        state["attempts"][attempt_id] = updated.to_dict()
        state["audit_events"].append(event.to_dict())
        self._write_state(state)
        return ExecutionAttemptResult(status=target_status, attempt=updated, existing_attempt=None, reasons=(_info(event_type, "attempt.status"),))

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION, "attempts": {}, "audit_events": []}
        with self.path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return {
            "schema_version": state.get("schema_version") or EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION,
            "attempts": dict(state.get("attempts") or {}),
            "audit_events": list(state.get("audit_events") or []),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        rendered = json.dumps(_json_safe(state), sort_keys=True, indent=2, ensure_ascii=True)
        decoded = json.loads(rendered)
        if _contains_registry_secret(decoded) or _contains_forbidden_data(decoded):
            raise PlaybookValidationError("execution_attempt_ledger.unsafe_payload", "Execution attempt ledger must not persist unsafe data.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(rendered + "\n", encoding="utf-8")


def _open_reasons(claim: dict[str, Any], preparation: dict[str, Any], mode: str, now: str) -> list[ExecutionAttemptReason]:
    reasons: list[ExecutionAttemptReason] = []
    if not claim:
        reasons.append(_error("claim_missing", "claim"))
    elif str(claim.get("status") or "") != "claimed":
        reasons.append(_error(f"claim_{claim.get('status') or 'unsupported_status'}", "claim.status"))
    elif _parse_time(str(claim.get("lease_expires_at") or "")) <= _parse_time(now):
        reasons.append(_error("claim_expired", "claim.lease_expires_at"))
    if not preparation:
        reasons.append(_error("preparation_missing", "preparation"))
    elif str(preparation.get("store_status") or preparation.get("status") or "") != "ready":
        reasons.append(_error("preparation_not_ready", "preparation.status"))
    if claim and preparation:
        if str(claim.get("preparation_id") or "") != str(preparation.get("preparation_id") or ""):
            reasons.append(_error("claim_preparation_mismatch", "claim.preparation_id"))
        if str(claim.get("idempotency_key") or "") != str(preparation.get("idempotency_key") or ""):
            reasons.append(_error("idempotency_key_mismatch", "claim.idempotency_key"))
    if mode not in ATTEMPT_MODES:
        reasons.append(_error("unsupported_mode", "mode"))
    action = str(preparation.get("requested_action_kind") or "")
    if action not in SAFE_REQUESTED_ACTION_KINDS:
        reasons.append(_error("unsafe_action", "preparation.requested_action_kind"))
    reasons.extend(_redaction_reasons("claim", claim))
    reasons.extend(_redaction_reasons("preparation", preparation))
    return reasons


def _active_attempt(state: dict[str, Any], claim_id: str, preparation_id: str, mode: str) -> ExecutionAttemptRecord | None:
    matches = []
    for payload in state.get("attempts", {}).values():
        if payload.get("status") != "opened":
            continue
        if payload.get("claim_id") == claim_id and payload.get("preparation_id") == preparation_id and payload.get("mode") == mode:
            matches.append(payload)
    if not matches:
        return None
    return _attempt_from_dict(sorted(matches, key=lambda item: (str(item.get("started_at") or ""), str(item.get("attempt_id") or "")))[0])


def _attempt_from_payload(
    *,
    attempt_id: str,
    claim: dict[str, Any],
    preparation: dict[str, Any],
    mode: str,
    status: str,
    timestamp: str,
    completed_at: str,
    result: dict[str, Any],
    reasons: tuple[ExecutionAttemptReason, ...],
    actor: str | None,
) -> ExecutionAttemptRecord:
    record = ExecutionAttemptRecord(
        attempt_id=attempt_id,
        preparation_id=str(preparation.get("preparation_id") or claim.get("preparation_id") or ""),
        claim_id=str(claim.get("claim_id") or ""),
        idempotency_key=str(preparation.get("idempotency_key") or claim.get("idempotency_key") or ""),
        playbook_id=str(preparation.get("playbook_id") or ""),
        playbook_version=str(preparation.get("playbook_version") or ""),
        requested_action_kind=str(preparation.get("requested_action_kind") or ""),
        mode=mode,
        status=status,
        started_at=timestamp if status == "opened" else "",
        completed_at=completed_at,
        result=_json_safe(result),
        blocked_reasons=reasons,
        events=(),
        provenance={
            "actor": _safe_text(actor or ""),
            "attempt_ledger_schema_version": EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION,
            "claim_ref": {"claim_id": str(claim.get("claim_id") or ""), "schema_version": str(claim.get("schema_version") or "")},
            "preparation_ref": {
                "preparation_id": str(preparation.get("preparation_id") or ""),
                "schema_version": str(preparation.get("schema_version") or ""),
            },
        },
        redaction=ExecutionAttemptRedaction(),
    )
    _assert_attempt_safe(record.to_dict())
    return record


def _attempt_from_dict(payload: dict[str, Any]) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        attempt_id=str(payload.get("attempt_id") or ""),
        preparation_id=str(payload.get("preparation_id") or ""),
        claim_id=str(payload.get("claim_id") or ""),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        playbook_id=str(payload.get("playbook_id") or ""),
        playbook_version=str(payload.get("playbook_version") or ""),
        requested_action_kind=str(payload.get("requested_action_kind") or ""),
        mode=str(payload.get("mode") or ""),
        status=str(payload.get("status") or ""),
        started_at=str(payload.get("started_at") or ""),
        completed_at=str(payload.get("completed_at") or ""),
        result=dict(payload.get("result") or {}),
        blocked_reasons=tuple(ExecutionAttemptReason(**item) for item in payload.get("blocked_reasons") or ()),
        events=tuple(_event_from_dict(item) for item in payload.get("events") or ()),
        provenance=dict(payload.get("provenance") or {}),
        redaction=ExecutionAttemptRedaction(**dict(payload.get("redaction") or {})),
        schema_version=str(payload.get("schema_version") or EXECUTION_ATTEMPT_SCHEMA_VERSION),
    )


def _event_from_dict(payload: dict[str, Any]) -> ExecutionAttemptEvent:
    return ExecutionAttemptEvent(
        event_id=str(payload.get("event_id") or ""),
        attempt_id=str(payload.get("attempt_id") or ""),
        preparation_id=str(payload.get("preparation_id") or ""),
        claim_id=str(payload.get("claim_id") or ""),
        event_type=str(payload.get("event_type") or ""),
        reason=str(payload.get("reason") or ""),
        timestamp=str(payload.get("timestamp") or ""),
        provenance=dict(payload.get("provenance") or {}),
        redaction=ExecutionAttemptRedaction(**dict(payload.get("redaction") or {})),
        sequence=int(payload.get("sequence") or 0),
        schema_version=str(payload.get("schema_version") or EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION),
    )


def _event(
    *,
    attempt: ExecutionAttemptRecord,
    event_type: str,
    reason: str,
    timestamp: str,
    sequence: int,
) -> ExecutionAttemptEvent:
    event = ExecutionAttemptEvent(
        event_id=_event_id(event_type, attempt.attempt_id, timestamp, sequence),
        attempt_id=attempt.attempt_id,
        preparation_id=attempt.preparation_id,
        claim_id=attempt.claim_id,
        event_type=event_type,
        reason=_safe_text(reason),
        timestamp=timestamp,
        sequence=sequence,
        provenance={"attempt_ledger_schema_version": EXECUTION_ATTEMPT_LEDGER_SCHEMA_VERSION},
        redaction=ExecutionAttemptRedaction(),
    )
    _assert_attempt_safe(event.to_dict(), allow_event=True)
    return event


def _redaction_reasons(label: str, payload: dict[str, Any]) -> list[ExecutionAttemptReason]:
    if not payload:
        return []
    reasons: list[ExecutionAttemptReason] = []
    redaction = payload.get("redaction") or {}
    for key in (
        "approval_state_mutated",
        "execution_started",
        "external_write_used",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            reasons.append(_error("unsafe_redaction", f"{label}.redaction.{key}"))
    if _contains_forbidden_data(payload):
        reasons.append(_error("unsafe_redaction", label))
    return reasons


def _attempt_id(claim: dict[str, Any], preparation: dict[str, Any], mode: str, timestamp: str, index: int) -> str:
    seed = {
        "claim_id": claim.get("claim_id") or "",
        "index": index,
        "mode": mode,
        "preparation_id": preparation.get("preparation_id") or claim.get("preparation_id") or "",
        "timestamp": timestamp,
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"execution_attempt_{digest[:32]}"


def _event_id(event_type: str, attempt_id: str, timestamp: str, sequence: int) -> str:
    digest = hashlib.sha256(f"{event_type}:{attempt_id}:{timestamp}:{sequence}".encode("utf-8")).hexdigest()
    return f"execution_attempt_audit_{digest[:32]}"


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _info(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionAttemptReason:
    return ExecutionAttemptReason(reason_code=reason_code, severity="info", subject_ref=subject_ref, details=details or {})


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionAttemptReason:
    return ExecutionAttemptReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _reason_key(reason: ExecutionAttemptReason) -> tuple[str, str, str]:
    return (reason.severity, reason.subject_ref, reason.reason_code)


def _safe_value(value: Any) -> Any:
    rendered = _json_safe(value)
    if _contains_forbidden_data({"value": rendered}):
        return "redacted"
    return rendered


def _safe_text(value: str) -> str:
    rendered = str(value or "")
    if _contains_registry_secret({"value": rendered}) or _contains_forbidden_data({"value": rendered}):
        return "redacted"
    return rendered


def _assert_attempt_safe(payload: dict[str, Any], *, allow_event: bool = False) -> None:
    if "status" in payload and str(payload.get("status") or "") not in ATTEMPT_STATUSES:
        raise PlaybookValidationError("execution_attempt_ledger.invalid_status", "Execution attempt status is invalid.")
    if "mode" in payload and str(payload.get("mode") or "") not in ATTEMPT_MODES:
        raise PlaybookValidationError("execution_attempt_ledger.invalid_mode", "Execution attempt mode is invalid.")
    forbidden_statuses = {"executed", "failed_production", "mutated", "production_completed", "production_failed", "published"}
    if str(payload.get("status") or "") in forbidden_statuses:
        raise PlaybookValidationError("execution_attempt_ledger.production_status", "Production attempt statuses are not supported.")
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("execution_attempt_ledger.unsafe_payload", "Execution attempt contains unsafe data.")
    redaction = payload.get("redaction") or {}
    for key in (
        "ai_call_used",
        "approval_state_mutated",
        "external_write_used",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError("execution_attempt_ledger.unsafe_redaction", "Execution attempt redaction is unsafe.")
    if not allow_event and payload.get("result"):
        result = payload.get("result") or {}
        for key in ("ai_call_used", "external_write_used", "production_mutation_used", "raw_access_used", "side_effects"):
            if result.get(key, False) is not False:
                raise PlaybookValidationError("execution_attempt_ledger.side_effect", "Execution attempt result recorded a side effect.")


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = (
        "Authorization",
        "Bearer",
        "SECRET_CANARY",
        "access_token",
        "api_key",
        "oauth_token",
        "raw_metrics_payload",
        "raw_transcript_body",
        "refresh_token",
    )
    markers = (
        "ai_invoked",
        "browser_automation_invoked",
        "external_write_invoked",
        "network_invoked",
        "production_executor_invoked",
        "scraping_invoked",
    )
    return any(item in rendered for item in forbidden) or any(item in rendered.lower() for item in markers)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
