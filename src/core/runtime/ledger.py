from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from .errors import ExecutionLedgerError
from .events import utc_now_iso
from .identifiers import validate_runtime_id
from .installs import SECRET_VALUE_FRAGMENTS


class ExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


TERMINAL_STATES = {
    ExecutionState.SUCCEEDED.value,
    ExecutionState.FAILED.value,
    ExecutionState.CANCELLED.value,
    ExecutionState.SKIPPED.value,
}
ALLOWED_TRANSITIONS = {
    ExecutionState.PENDING.value: {
        ExecutionState.RUNNING.value,
        ExecutionState.CANCELLED.value,
        ExecutionState.SKIPPED.value,
    },
    ExecutionState.RUNNING.value: {
        ExecutionState.WAITING.value,
        ExecutionState.SUCCEEDED.value,
        ExecutionState.FAILED.value,
        ExecutionState.CANCELLED.value,
    },
    ExecutionState.WAITING.value: {
        ExecutionState.RUNNING.value,
        ExecutionState.FAILED.value,
        ExecutionState.CANCELLED.value,
    },
}


def generate_execution_id() -> str:
    return f"exec_{uuid4().hex}"


def generate_node_execution_id() -> str:
    return f"node_exec_{uuid4().hex}"


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _assert_no_secret_values(value: dict[str, Any]) -> None:
    for key in value:
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in SECRET_VALUE_FRAGMENTS) and not lowered.endswith("_ref"):
            raise ExecutionLedgerError(
                "ledger.secret_value",
                "Execution ledger metadata may contain references, but not secret-shaped values.",
                {"field": key},
            )


@dataclass(frozen=True)
class ExecutionRecord:
    deployment_id: str
    playbook_id: str
    playbook_version: str
    trigger_event_id: str = ""
    correlation_id: str = ""
    trace_id: str = ""
    state: str = ExecutionState.PENDING.value
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    finished_at: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_id: str = field(default_factory=generate_execution_id)

    def __post_init__(self) -> None:
        validate_runtime_id(self.execution_id, field_name="execution_id")
        ExecutionState(self.state)
        _assert_no_secret_values(self.metadata)
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "deployment_id": self.deployment_id,
            "execution_id": self.execution_id,
            "finished_at": self.finished_at,
            "idempotency_key": self.idempotency_key,
            "metadata": _json_safe(self.metadata),
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
            "started_at": self.started_at,
            "state": self.state,
            "trace_id": self.trace_id,
            "trigger_event_id": self.trigger_event_id,
        }


@dataclass(frozen=True)
class NodeExecutionRecord:
    execution_id: str
    node_id: str
    state: str = ExecutionState.PENDING.value
    attempt: int = 1
    started_at: str = ""
    finished_at: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    node_execution_id: str = field(default_factory=generate_node_execution_id)

    def __post_init__(self) -> None:
        validate_runtime_id(self.node_execution_id, field_name="node_execution_id")
        ExecutionState(self.state)
        if self.attempt < 1:
            raise ExecutionLedgerError("ledger.invalid_attempt", "Node execution attempt must be positive.")
        _assert_no_secret_values(self.metadata)
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "execution_id": self.execution_id,
            "finished_at": self.finished_at,
            "metadata": _json_safe(self.metadata),
            "node_execution_id": self.node_execution_id,
            "node_id": self.node_id,
            "started_at": self.started_at,
            "state": self.state,
        }


@dataclass(frozen=True)
class ExecutionTransition:
    record_id: str
    record_type: str
    from_state: str
    to_state: str
    occurred_at: str
    actor: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "from_state": self.from_state,
            "metadata": _json_safe(self.metadata),
            "occurred_at": self.occurred_at,
            "record_id": self.record_id,
            "record_type": self.record_type,
            "to_state": self.to_state,
        }


class ExecutionLedger(Protocol):
    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord: ...

    def get_execution(self, execution_id: str) -> ExecutionRecord | None: ...

    def record_transition(
        self, execution_id: str, state: str, *, actor: str = "", metadata: dict[str, Any] | None = None
    ) -> ExecutionRecord: ...

    def create_node_execution(
        self, execution_id: str, node_id: str, *, metadata: dict[str, Any] | None = None
    ) -> NodeExecutionRecord: ...

    def record_node_transition(
        self,
        node_execution_id: str,
        state: str,
        *,
        actor: str = "",
        error_code: str = "",
        error_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NodeExecutionRecord: ...

    def list_node_executions(self, execution_id: str) -> list[NodeExecutionRecord]: ...


@dataclass
class InMemoryExecutionLedger:
    executions: dict[str, ExecutionRecord] = field(default_factory=dict)
    node_executions: dict[str, NodeExecutionRecord] = field(default_factory=dict)
    transitions: list[ExecutionTransition] = field(default_factory=list)
    idempotency_index: dict[str, str] = field(default_factory=dict)

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        if record.execution_id in self.executions:
            raise ExecutionLedgerError(
                "ledger.execution_exists",
                "Execution already exists.",
                {"execution_id": record.execution_id},
            )
        if record.idempotency_key and record.idempotency_key in self.idempotency_index:
            return self.executions[self.idempotency_index[record.idempotency_key]]
        self.executions[record.execution_id] = record
        if record.idempotency_key:
            self.idempotency_index[record.idempotency_key] = record.execution_id
        self.transitions.append(
            ExecutionTransition(
                record_id=record.execution_id,
                record_type="execution",
                from_state="",
                to_state=record.state,
                occurred_at=record.created_at,
                metadata={"created": True},
            )
        )
        return record

    def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        return self.executions.get(execution_id)

    def record_transition(
        self, execution_id: str, state: str, *, actor: str = "", metadata: dict[str, Any] | None = None
    ) -> ExecutionRecord:
        record = self.executions.get(execution_id)
        if record is None:
            raise ExecutionLedgerError(
                "ledger.execution_missing", "Execution is missing.", {"execution_id": execution_id}
            )
        next_state = ExecutionState(state).value
        _validate_transition(record.state, next_state)
        now = utc_now_iso()
        updated = replace(
            record,
            state=next_state,
            started_at=record.started_at or (now if next_state == ExecutionState.RUNNING.value else ""),
            finished_at=now if next_state in TERMINAL_STATES else record.finished_at,
        )
        self.executions[execution_id] = updated
        self.transitions.append(
            ExecutionTransition(
                record_id=execution_id,
                record_type="execution",
                from_state=record.state,
                to_state=next_state,
                occurred_at=now,
                actor=actor,
                metadata=_json_safe(metadata or {}),
            )
        )
        return updated

    def create_node_execution(
        self, execution_id: str, node_id: str, *, metadata: dict[str, Any] | None = None
    ) -> NodeExecutionRecord:
        if execution_id not in self.executions:
            raise ExecutionLedgerError(
                "ledger.execution_missing", "Execution is missing.", {"execution_id": execution_id}
            )
        attempt = 1 + max(
            (
                item.attempt
                for item in self.node_executions.values()
                if item.execution_id == execution_id and item.node_id == node_id
            ),
            default=0,
        )
        record = NodeExecutionRecord(
            execution_id=execution_id, node_id=node_id, attempt=attempt, metadata=metadata or {}
        )
        self.node_executions[record.node_execution_id] = record
        self.transitions.append(
            ExecutionTransition(
                record_id=record.node_execution_id,
                record_type="node_execution",
                from_state="",
                to_state=record.state,
                occurred_at=utc_now_iso(),
                metadata={"created": True},
            )
        )
        return record

    def record_node_transition(
        self,
        node_execution_id: str,
        state: str,
        *,
        actor: str = "",
        error_code: str = "",
        error_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NodeExecutionRecord:
        record = self.node_executions.get(node_execution_id)
        if record is None:
            raise ExecutionLedgerError(
                "ledger.node_execution_missing",
                "Node execution is missing.",
                {"node_execution_id": node_execution_id},
            )
        next_state = ExecutionState(state).value
        _validate_transition(record.state, next_state)
        now = utc_now_iso()
        updated = replace(
            record,
            state=next_state,
            started_at=record.started_at or (now if next_state == ExecutionState.RUNNING.value else ""),
            finished_at=now if next_state in TERMINAL_STATES else record.finished_at,
            error_code=error_code or record.error_code,
            error_message=error_message or record.error_message,
        )
        self.node_executions[node_execution_id] = updated
        self.transitions.append(
            ExecutionTransition(
                record_id=node_execution_id,
                record_type="node_execution",
                from_state=record.state,
                to_state=next_state,
                occurred_at=now,
                actor=actor,
                metadata=_json_safe(metadata or {}),
            )
        )
        return updated

    def list_node_executions(self, execution_id: str) -> list[NodeExecutionRecord]:
        return sorted(
            [item for item in self.node_executions.values() if item.execution_id == execution_id],
            key=lambda item: (item.node_id, item.attempt, item.node_execution_id),
        )

    def list_transitions(self, *, record_id: str = "") -> list[ExecutionTransition]:
        if not record_id:
            return list(self.transitions)
        return [item for item in self.transitions if item.record_id == record_id]


def _validate_transition(current: str, next_state: str) -> None:
    if current == next_state:
        return
    if current in TERMINAL_STATES:
        raise ExecutionLedgerError(
            "ledger.terminal_transition",
            "Terminal execution state cannot transition.",
            {"from_state": current, "to_state": next_state},
        )
    if next_state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ExecutionLedgerError(
            "ledger.invalid_transition",
            "Execution state transition is not allowed.",
            {"from_state": current, "to_state": next_state},
        )
