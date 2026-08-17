from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .execution_preparation import EXECUTION_PREPARATION_SCHEMA_VERSION, ExecutionPreparationRecord
from .playbook_registry import _contains_registry_secret

EXECUTION_PREPARATION_STORE_SCHEMA_VERSION = "execution-preparation-store.v1"

PREPARATION_STORE_STATUSES = ("blocked", "cancelled", "needs_review", "ready", "stale")
TERMINAL_PREPARATION_STATUSES = {"cancelled", "stale"}


@dataclass(frozen=True)
class ExecutionPreparationAuditRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    execution_started: bool = False
    production_mutation_used: bool = False


@dataclass(frozen=True)
class ExecutionPreparationAuditEvent:
    event_id: str
    preparation_id: str
    idempotency_key: str
    event_type: str
    actor: str
    reason: str
    timestamp: str
    provenance: dict[str, Any]
    redaction: ExecutionPreparationAuditRedaction
    sequence: int = 0
    schema_version: str = EXECUTION_PREPARATION_STORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionPreparationStoreTransitionResult:
    record: dict[str, Any]
    changed: bool
    status: str
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionPreparationStore:
    def __init__(self, path: Path | str, *, clock=utc_now_iso):
        self.path = Path(path)
        self.clock = clock

    def save(
        self,
        record: ExecutionPreparationRecord | dict[str, Any],
        *,
        actor: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload = _payload(record)
        _assert_preparation_record_safe(payload)
        key = self.idempotency_key(payload)
        state = self._load_state()
        existing_id = state["idempotency_index"].get(key)
        timestamp = self.clock()
        safe_actor = _safe_text(actor or "")
        safe_reason = _safe_text(reason or "")
        if existing_id and existing_id in state["records"]:
            state["audit_events"].append(
                _audit_event(
                    preparation_id=existing_id,
                    idempotency_key=key,
                    event_type="duplicate_detected",
                    actor=safe_actor,
                    reason=safe_reason or "duplicate_detected",
                    timestamp=timestamp,
                    sequence=len(state["audit_events"]),
                ).to_dict()
            )
            self._write_state(state)
            return _json_safe(state["records"][existing_id])

        persisted = {
            **payload,
            "idempotency_key": key,
            "store_schema_version": EXECUTION_PREPARATION_STORE_SCHEMA_VERSION,
            "store_status": str(payload.get("status") or ""),
            "updated_at": timestamp,
        }
        state["records"][payload["preparation_id"]] = persisted
        state["idempotency_index"][key] = payload["preparation_id"]
        state["audit_events"].append(
            _audit_event(
                preparation_id=payload["preparation_id"],
                idempotency_key=key,
                event_type="saved",
                actor=safe_actor,
                reason=safe_reason or "saved",
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            ).to_dict()
        )
        self._write_state(state)
        return _json_safe(persisted)

    def get(self, preparation_id: str) -> dict[str, Any] | None:
        record = self._load_state()["records"].get(preparation_id)
        return _json_safe(record) if record is not None else None

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        state = self._load_state()
        preparation_id = state["idempotency_index"].get(key)
        if not preparation_id:
            return None
        record = state["records"].get(preparation_id)
        return _json_safe(record) if record is not None else None

    def list(
        self,
        *,
        status: str | None = None,
        playbook_id: str | None = None,
        approval_id: str | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self._load_state()["records"].values())
        if status is not None:
            records = [item for item in records if item.get("store_status", item.get("status")) == status]
        if playbook_id is not None:
            records = [item for item in records if item.get("playbook_id") == playbook_id]
        if approval_id is not None:
            records = [item for item in records if item.get("approval_id") == approval_id]
        return _json_safe(sorted(records, key=lambda item: (str(item.get("created_at") or ""), str(item.get("preparation_id") or ""))))

    def audit_events(self, preparation_id: str | None = None) -> list[dict[str, Any]]:
        events = self._load_state()["audit_events"]
        if preparation_id is not None:
            events = [item for item in events if item.get("preparation_id") == preparation_id]
        return _json_safe(
            sorted(
                events,
                key=lambda item: (
                    int(item.get("sequence") or 0),
                    str(item.get("timestamp") or ""),
                    str(item.get("event_id") or ""),
                ),
            )
        )

    def mark_cancelled(self, preparation_id: str, *, actor: str | None = None, reason: str | None = None) -> ExecutionPreparationStoreTransitionResult:
        return self._transition(preparation_id, "cancelled", actor=actor, reason=reason)

    def mark_stale(self, preparation_id: str, *, actor: str | None = None, reason: str | None = None) -> ExecutionPreparationStoreTransitionResult:
        return self._transition(preparation_id, "stale", actor=actor, reason=reason)

    def idempotency_key(self, record: ExecutionPreparationRecord | dict[str, Any]) -> str:
        payload = _payload(record)
        stable = {
            "approval_id": str(payload.get("approval_id") or ""),
            "eligibility_decision_id": str(payload.get("eligibility_decision_id") or ""),
            "forbidden_side_effects": sorted(str(item) for item in payload.get("forbidden_side_effects") or ()),
            "plan_fingerprint": str(payload.get("plan_fingerprint") or ""),
            "plan_id": str(payload.get("plan_id") or ""),
            "playbook_id": str(payload.get("playbook_id") or ""),
            "playbook_version": str(payload.get("playbook_version") or ""),
            "promotion_decision_id": str(payload.get("promotion_decision_id") or ""),
            "requested_action_kind": str(payload.get("requested_action_kind") or ""),
            "required_capabilities": sorted(str(item) for item in payload.get("required_capabilities") or ()),
            "subject_scope": _strip_volatile_scope(payload.get("subject_scope") or {}),
        }
        rendered = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        return f"execution_preparation_idempotency_{digest[:32]}"

    def _transition(
        self,
        preparation_id: str,
        target_status: str,
        *,
        actor: str | None,
        reason: str | None,
    ) -> ExecutionPreparationStoreTransitionResult:
        state = self._load_state()
        current = state["records"].get(preparation_id)
        if current is None:
            raise KeyError(preparation_id)
        current_status = str(current.get("store_status") or current.get("status") or "")
        timestamp = self.clock()
        safe_actor = _safe_text(actor or "")
        safe_reason = _safe_text(reason or "")
        if not _can_transition(current_status, target_status):
            state["audit_events"].append(
                _audit_event(
                    preparation_id=preparation_id,
                    idempotency_key=str(current.get("idempotency_key") or ""),
                    event_type="invalid_transition_attempted",
                    actor=safe_actor,
                    reason=safe_reason or "invalid_transition_attempted",
                    timestamp=timestamp,
                    sequence=len(state["audit_events"]),
                ).to_dict()
            )
            self._write_state(state)
            return ExecutionPreparationStoreTransitionResult(
                record=_json_safe(current),
                changed=False,
                status=current_status,
                reason_code="invalid_transition_attempted",
            )

        updated = {**current, "store_status": target_status, "status": target_status, "updated_at": timestamp}
        _assert_preparation_record_safe(updated, allow_terminal_status=True)
        state["records"][preparation_id] = updated
        state["audit_events"].append(
            _audit_event(
                preparation_id=preparation_id,
                idempotency_key=str(current.get("idempotency_key") or ""),
                event_type=target_status,
                actor=safe_actor,
                reason=safe_reason or target_status,
                timestamp=timestamp,
                sequence=len(state["audit_events"]),
            ).to_dict()
        )
        self._write_state(state)
        return ExecutionPreparationStoreTransitionResult(
            record=_json_safe(updated),
            changed=True,
            status=target_status,
            reason_code=target_status,
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": EXECUTION_PREPARATION_STORE_SCHEMA_VERSION,
                "records": {},
                "idempotency_index": {},
                "audit_events": [],
            }
        with self.path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return {
            "schema_version": state.get("schema_version") or EXECUTION_PREPARATION_STORE_SCHEMA_VERSION,
            "records": dict(state.get("records") or {}),
            "idempotency_index": dict(state.get("idempotency_index") or {}),
            "audit_events": list(state.get("audit_events") or []),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(_json_safe(state), sort_keys=True, indent=2, ensure_ascii=True)
        if _contains_registry_secret(json.loads(rendered)):
            raise PlaybookValidationError("execution_preparation_store.secret_value", "Preparation store must not persist secrets.")
        if _contains_forbidden_data(json.loads(rendered)):
            raise PlaybookValidationError("execution_preparation_store.unsafe_payload", "Preparation store contains forbidden data.")
        self.path.write_text(rendered + "\n", encoding="utf-8")


def _can_transition(current_status: str, target_status: str) -> bool:
    if current_status in TERMINAL_PREPARATION_STATUSES:
        return False
    if target_status not in TERMINAL_PREPARATION_STATUSES:
        return False
    if current_status in {"ready", "needs_review"}:
        return True
    if current_status == "blocked" and target_status == "stale":
        return True
    return False


def _audit_event(
    *,
    preparation_id: str,
    idempotency_key: str,
    event_type: str,
    actor: str,
    reason: str,
    timestamp: str,
    sequence: int,
) -> ExecutionPreparationAuditEvent:
    return ExecutionPreparationAuditEvent(
        event_id=_audit_event_id(event_type, preparation_id, timestamp, sequence),
        preparation_id=preparation_id,
        idempotency_key=idempotency_key,
        event_type=event_type,
        actor=actor,
        reason=reason,
        timestamp=timestamp,
        sequence=sequence,
        provenance={"store_schema_version": EXECUTION_PREPARATION_STORE_SCHEMA_VERSION},
        redaction=ExecutionPreparationAuditRedaction(),
    )


def _audit_event_id(event_type: str, preparation_id: str, timestamp: str, sequence: int) -> str:
    digest = hashlib.sha256(f"{event_type}:{preparation_id}:{timestamp}:{sequence}".encode("utf-8")).hexdigest()
    return f"execution_preparation_audit_{digest[:32]}"


def _payload(value: ExecutionPreparationRecord | dict[str, Any]) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _strip_volatile_scope(scope: dict[str, Any]) -> dict[str, Any]:
    volatile = {"preparation_id", "created_at", "updated_at", "local_path"}
    return {key: _json_safe(value) for key, value in sorted(scope.items()) if key not in volatile}


def _assert_preparation_record_safe(payload: dict[str, Any], *, allow_terminal_status: bool = False) -> None:
    status = str(payload.get("store_status") or payload.get("status") or "")
    allowed_statuses = set(PREPARATION_STORE_STATUSES if allow_terminal_status else ("ready", "blocked", "needs_review"))
    if status not in allowed_statuses:
        raise PlaybookValidationError("execution_preparation_store.invalid_status", "Preparation store status is invalid.")
    if str(payload.get("schema_version") or "") != EXECUTION_PREPARATION_SCHEMA_VERSION:
        raise PlaybookValidationError("execution_preparation_store.schema", "Unsupported execution preparation schema.")
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("execution_preparation_store.unsafe_payload", "Preparation store must not persist unsafe data.")
    forbidden_statuses = {"claim", "claimed", "executing", "executed", "running"}
    if status in forbidden_statuses:
        raise PlaybookValidationError("execution_preparation_store.execution_status", "Execution statuses are not supported.")
    redaction = payload.get("redaction") or {}
    for key in ("raw_metrics_included", "raw_transcript_included", "secrets_included", "provider_headers_included"):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError("execution_preparation_store.unsafe_redaction", "Preparation store redaction is unsafe.")
    for key in ("approval_state_mutated", "execution_started", "production_mutation_used"):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError("execution_preparation_store.side_effect", "Preparation store recorded a forbidden side effect.")


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
