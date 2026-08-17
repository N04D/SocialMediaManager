from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .execution_preparation_store import ExecutionPreparationStore
from .playbook_registry import _contains_registry_secret

EXECUTION_CLAIM_SCHEMA_VERSION = "execution-claim.v1"
EXECUTION_CLAIM_STORE_SCHEMA_VERSION = "execution-claim-store.v1"

CLAIM_STATUSES = ("claimed", "expired", "rejected", "released")
TERMINAL_CLAIM_STATUSES = {"expired", "rejected", "released"}


@dataclass(frozen=True)
class ExecutionClaimPolicy:
    policy_id: str = "execution-claim-default"
    version: str = "1.0.0"
    lease_seconds: int = 900
    allow_reclaim_expired: bool = True
    require_ready_status: bool = True
    allowed_claimant_kinds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionClaimRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    execution_started: bool = False
    production_mutation_used: bool = False


@dataclass(frozen=True)
class ExecutionClaimReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionClaim:
    claim_id: str
    preparation_id: str
    idempotency_key: str
    claimant_id: str
    status: str
    lease_expires_at: str
    claimed_at: str
    released_at: str
    expired_at: str
    reason: str
    provenance: dict[str, Any]
    redaction: ExecutionClaimRedaction
    schema_version: str = EXECUTION_CLAIM_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionClaimResult:
    status: str
    claim: ExecutionClaim | None
    existing_claim: ExecutionClaim | None
    reasons: tuple[ExecutionClaimReason, ...]

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionClaimAuditEvent:
    event_id: str
    claim_id: str
    preparation_id: str
    claimant_id: str
    event_type: str
    reason: str
    timestamp: str
    provenance: dict[str, Any]
    redaction: ExecutionClaimRedaction
    sequence: int = 0
    schema_version: str = EXECUTION_CLAIM_STORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionClaimStore:
    def __init__(self, path: Path | str, *, preparation_store: ExecutionPreparationStore, clock=utc_now_iso):
        self.path = Path(path)
        self.preparation_store = preparation_store
        self.clock = clock

    def claim(
        self,
        preparation_id: str,
        claimant_id: str,
        *,
        policy: ExecutionClaimPolicy | None = None,
        now: str | None = None,
    ) -> ExecutionClaimResult:
        selected_policy = policy or ExecutionClaimPolicy()
        timestamp = now or self.clock()
        state = self._load_state()
        claimant = _safe_text(claimant_id)
        reasons = _claimant_reasons(claimant_id, selected_policy)
        preparation = self.preparation_store.get(preparation_id)
        if preparation is None:
            reasons.append(_error("preparation_not_found", "preparation_id"))
        else:
            reasons.extend(_preparation_reasons(preparation, selected_policy))
        active = self.get_active_for_preparation(preparation_id, now=timestamp)
        if active is not None:
            reasons.append(_error("already_claimed", "preparation_id", {"claim_id": active.claim_id}))
        terminal = _latest_terminal_claim(state, preparation_id)
        if terminal is not None and not selected_policy.allow_reclaim_expired:
            reasons.append(_error("claim_released" if terminal.status == "released" else "claim_expired", "preparation_id"))
        if selected_policy.lease_seconds <= 0:
            reasons.append(_error("lease_invalid", "policy.lease_seconds"))

        if reasons:
            rejected = _claim_from_payload(
                claim_id=_claim_id(preparation_id, claimant, timestamp, len(state["claims"])),
                preparation_id=preparation_id,
                idempotency_key=str((preparation or {}).get("idempotency_key") or ""),
                claimant_id=claimant,
                status="rejected",
                timestamp=timestamp,
                lease_expires_at="",
                reason=";".join(sorted(reason.reason_code for reason in reasons)),
                policy=selected_policy,
            )
            state["claims"][rejected.claim_id] = rejected.to_dict()
            state["audit_events"].append(
                _audit_event(
                    claim=rejected,
                    event_type="duplicate_claim_rejected" if active is not None else "claim_rejected",
                    timestamp=timestamp,
                    sequence=len(state["audit_events"]),
                ).to_dict()
            )
            self._write_state(state)
            return ExecutionClaimResult(status="rejected", claim=rejected, existing_claim=active, reasons=tuple(sorted(reasons, key=_reason_key)))

        lease_expires_at = _format_time(_parse_time(timestamp) + timedelta(seconds=selected_policy.lease_seconds))
        claim = _claim_from_payload(
            claim_id=_claim_id(preparation_id, claimant, timestamp, len(state["claims"])),
            preparation_id=preparation_id,
            idempotency_key=str(preparation.get("idempotency_key") or ""),
            claimant_id=claimant,
            status="claimed",
            timestamp=timestamp,
            lease_expires_at=lease_expires_at,
            reason="claimed",
            policy=selected_policy,
        )
        state["claims"][claim.claim_id] = claim.to_dict()
        state["audit_events"].append(
            _audit_event(
                claim=claim,
                event_type="claim_created",
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            ).to_dict()
        )
        self._write_state(state)
        return ExecutionClaimResult(status="claimed", claim=claim, existing_claim=None, reasons=(_info("claim_created", "claim"),))

    def get(self, claim_id: str) -> ExecutionClaim | None:
        payload = self._load_state()["claims"].get(claim_id)
        return _claim_from_dict(payload) if payload is not None else None

    def get_active_for_preparation(self, preparation_id: str, *, now: str | None = None) -> ExecutionClaim | None:
        timestamp = now or self.clock()
        active = []
        for payload in self._load_state()["claims"].values():
            if payload.get("preparation_id") != preparation_id or payload.get("status") != "claimed":
                continue
            if _parse_time(str(payload.get("lease_expires_at") or "")) > _parse_time(timestamp):
                active.append(payload)
        if not active:
            return None
        selected = sorted(active, key=lambda item: (str(item.get("claimed_at") or ""), str(item.get("claim_id") or "")))[0]
        return _claim_from_dict(selected)

    def release(self, claim_id: str, *, claimant_id: str | None = None, reason: str | None = None, now: str | None = None) -> ExecutionClaimResult:
        return self._transition(claim_id, "released", claimant_id=claimant_id, reason=reason, now=now)

    def expire(self, claim_id: str, *, now: str | None = None) -> ExecutionClaimResult:
        return self._transition(claim_id, "expired", claimant_id=None, reason="claim_expired", now=now, require_lease_elapsed=True)

    def list(
        self,
        *,
        status: str | None = None,
        preparation_id: str | None = None,
        claimant_id: str | None = None,
    ) -> tuple[ExecutionClaim, ...]:
        claims = [_claim_from_dict(item) for item in self._load_state()["claims"].values()]
        if status is not None:
            claims = [item for item in claims if item.status == status]
        if preparation_id is not None:
            claims = [item for item in claims if item.preparation_id == preparation_id]
        if claimant_id is not None:
            claims = [item for item in claims if item.claimant_id == _safe_text(claimant_id)]
        return tuple(sorted(claims, key=lambda item: (item.claimed_at, item.claim_id)))

    def audit_events(self, *, preparation_id: str | None = None, claim_id: str | None = None) -> tuple[dict[str, Any], ...]:
        events = self._load_state()["audit_events"]
        if preparation_id is not None:
            events = [item for item in events if item.get("preparation_id") == preparation_id]
        if claim_id is not None:
            events = [item for item in events if item.get("claim_id") == claim_id]
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
        claim_id: str,
        target_status: str,
        *,
        claimant_id: str | None,
        reason: str | None,
        now: str | None,
        require_lease_elapsed: bool = False,
    ) -> ExecutionClaimResult:
        state = self._load_state()
        payload = state["claims"].get(claim_id)
        if payload is None:
            reasons = (_error("claim_not_found", "claim_id"),)
            return ExecutionClaimResult(status="rejected", claim=None, existing_claim=None, reasons=reasons)
        current = _claim_from_dict(payload)
        timestamp = now or self.clock()
        reasons: list[ExecutionClaimReason] = []
        if current.status != "claimed":
            reasons.append(_error("invalid_transition_attempted", "claim.status", {"status": current.status}))
        if claimant_id is not None and _safe_text(claimant_id) != current.claimant_id:
            reasons.append(_error("invalid_claimant", "claimant_id"))
        if require_lease_elapsed and _parse_time(timestamp) < _parse_time(current.lease_expires_at):
            reasons.append(_error("claim_not_expired", "lease_expires_at"))
        if reasons:
            state["audit_events"].append(
                _audit_event(
                    claim=current,
                    event_type="invalid_transition_attempted",
                    timestamp=timestamp,
                    sequence=len(state["audit_events"]),
                    reason=";".join(sorted(reason.reason_code for reason in reasons)),
                ).to_dict()
            )
            self._write_state(state)
            return ExecutionClaimResult(status=current.status, claim=current, existing_claim=None, reasons=tuple(sorted(reasons, key=_reason_key)))

        updated_payload = current.to_dict()
        updated_payload.update(
            {
                "status": target_status,
                "reason": _safe_text(reason or target_status),
                "released_at": timestamp if target_status == "released" else current.released_at,
                "expired_at": timestamp if target_status == "expired" else current.expired_at,
            }
        )
        updated = _claim_from_dict(updated_payload)
        state["claims"][claim_id] = updated.to_dict()
        state["audit_events"].append(
            _audit_event(
                claim=updated,
                event_type="claim_released" if target_status == "released" else "claim_expired",
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            ).to_dict()
        )
        self._write_state(state)
        return ExecutionClaimResult(status=target_status, claim=updated, existing_claim=None, reasons=(_info(f"claim_{target_status}", "claim.status"),))

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": EXECUTION_CLAIM_STORE_SCHEMA_VERSION, "claims": {}, "audit_events": []}
        with self.path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return {
            "schema_version": state.get("schema_version") or EXECUTION_CLAIM_STORE_SCHEMA_VERSION,
            "claims": dict(state.get("claims") or {}),
            "audit_events": list(state.get("audit_events") or []),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        rendered = json.dumps(_json_safe(state), sort_keys=True, indent=2, ensure_ascii=True)
        decoded = json.loads(rendered)
        if _contains_registry_secret(decoded) or _contains_forbidden_data(decoded):
            raise PlaybookValidationError("execution_claim_store.unsafe_payload", "Execution claim store must not persist unsafe data.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(rendered + "\n", encoding="utf-8")


def _preparation_reasons(payload: dict[str, Any], policy: ExecutionClaimPolicy) -> list[ExecutionClaimReason]:
    reasons: list[ExecutionClaimReason] = []
    status = str(payload.get("store_status") or payload.get("status") or "")
    if policy.require_ready_status and status != "ready":
        reasons.append(_error("preparation_not_ready", "preparation.status", {"status": status}))
    redaction = payload.get("redaction") or {}
    for key in ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included"):
        if redaction.get(key, False) is not False:
            reasons.append(_error("unsafe_redaction", f"preparation.redaction.{key}"))
    for key in ("approval_state_mutated", "execution_started", "production_mutation_used"):
        if redaction.get(key, False) is not False:
            reasons.append(_error("unsafe_redaction", f"preparation.redaction.{key}"))
    if _contains_forbidden_data(payload):
        reasons.append(_error("unsafe_redaction", "preparation"))
    return reasons


def _claimant_reasons(claimant_id: str, policy: ExecutionClaimPolicy) -> list[ExecutionClaimReason]:
    claimant = _safe_text(claimant_id)
    if not claimant or claimant == "redacted":
        return [_error("invalid_claimant", "claimant_id")]
    if policy.allowed_claimant_kinds:
        kind = claimant.split(":", 1)[0] if ":" in claimant else ""
        if kind not in policy.allowed_claimant_kinds:
            return [_error("invalid_claimant", "claimant_id", {"allowed_kinds": list(policy.allowed_claimant_kinds)})]
    return []


def _claim_from_payload(
    *,
    claim_id: str,
    preparation_id: str,
    idempotency_key: str,
    claimant_id: str,
    status: str,
    timestamp: str,
    lease_expires_at: str,
    reason: str,
    policy: ExecutionClaimPolicy,
) -> ExecutionClaim:
    claim = ExecutionClaim(
        claim_id=claim_id,
        preparation_id=preparation_id,
        idempotency_key=idempotency_key,
        claimant_id=claimant_id,
        status=status,
        lease_expires_at=lease_expires_at,
        claimed_at=timestamp if status == "claimed" else "",
        released_at="",
        expired_at="",
        reason=reason,
        provenance={
            "claim_store_schema_version": EXECUTION_CLAIM_STORE_SCHEMA_VERSION,
            "policy": policy.to_dict(),
        },
        redaction=ExecutionClaimRedaction(),
    )
    _assert_claim_safe(claim.to_dict())
    return claim


def _latest_terminal_claim(state: dict[str, Any], preparation_id: str) -> ExecutionClaim | None:
    claims = [
        _claim_from_dict(item)
        for item in state.get("claims", {}).values()
        if item.get("preparation_id") == preparation_id and item.get("status") in {"expired", "released"}
    ]
    if not claims:
        return None
    return sorted(claims, key=lambda item: (item.released_at or item.expired_at or item.claimed_at, item.claim_id))[-1]


def _claim_from_dict(payload: dict[str, Any]) -> ExecutionClaim:
    return ExecutionClaim(
        claim_id=str(payload.get("claim_id") or ""),
        preparation_id=str(payload.get("preparation_id") or ""),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        claimant_id=str(payload.get("claimant_id") or ""),
        status=str(payload.get("status") or ""),
        lease_expires_at=str(payload.get("lease_expires_at") or ""),
        claimed_at=str(payload.get("claimed_at") or ""),
        released_at=str(payload.get("released_at") or ""),
        expired_at=str(payload.get("expired_at") or ""),
        reason=str(payload.get("reason") or ""),
        provenance=dict(payload.get("provenance") or {}),
        redaction=ExecutionClaimRedaction(**dict(payload.get("redaction") or {})),
        schema_version=str(payload.get("schema_version") or EXECUTION_CLAIM_SCHEMA_VERSION),
    )


def _audit_event(
    *,
    claim: ExecutionClaim,
    event_type: str,
    timestamp: str,
    sequence: int,
    reason: str | None = None,
) -> ExecutionClaimAuditEvent:
    event = ExecutionClaimAuditEvent(
        event_id=_audit_event_id(event_type, claim.claim_id, timestamp, sequence),
        claim_id=claim.claim_id,
        preparation_id=claim.preparation_id,
        claimant_id=_safe_text(claim.claimant_id),
        event_type=event_type,
        reason=_safe_text(reason or claim.reason or event_type),
        timestamp=timestamp,
        sequence=sequence,
        provenance={"claim_store_schema_version": EXECUTION_CLAIM_STORE_SCHEMA_VERSION},
        redaction=ExecutionClaimRedaction(),
    )
    _assert_claim_safe(event.to_dict())
    return event


def _claim_id(preparation_id: str, claimant_id: str, timestamp: str, index: int) -> str:
    seed = {"claimant_id": claimant_id, "index": index, "preparation_id": preparation_id, "timestamp": timestamp}
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"execution_claim_{digest[:32]}"


def _audit_event_id(event_type: str, claim_id: str, timestamp: str, sequence: int) -> str:
    digest = hashlib.sha256(f"{event_type}:{claim_id}:{timestamp}:{sequence}".encode("utf-8")).hexdigest()
    return f"execution_claim_audit_{digest[:32]}"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _info(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionClaimReason:
    return ExecutionClaimReason(reason_code=reason_code, severity="info", subject_ref=subject_ref, details=details or {})


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionClaimReason:
    return ExecutionClaimReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _reason_key(reason: ExecutionClaimReason) -> tuple[str, str, str]:
    return (reason.severity, reason.subject_ref, reason.reason_code)


def _assert_claim_safe(payload: dict[str, Any]) -> None:
    if "status" in payload and str(payload.get("status") or "") not in CLAIM_STATUSES:
        raise PlaybookValidationError("execution_claim_store.invalid_status", "Execution claim status is invalid.")
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("execution_claim_store.unsafe_payload", "Execution claim contains unsafe data.")
    redaction = payload.get("redaction") or {}
    for key in (
        "approval_state_mutated",
        "execution_started",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError("execution_claim_store.unsafe_redaction", "Execution claim redaction is unsafe.")


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
    return any(item in rendered for item in forbidden)


def _safe_text(value: str) -> str:
    rendered = str(value or "")
    if _contains_registry_secret({"value": rendered}) or _contains_forbidden_data({"value": rendered}):
        return "redacted"
    return rendered


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
