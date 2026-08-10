from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from .errors import PlaybookExecutionError
from .events import EventEnvelope, utc_now_iso
from .identifiers import validate_runtime_id


class EventDeliveryState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    FAILED = "failed"


@dataclass(frozen=True)
class EventDispatchRecord:
    event_id: str
    deployment_id: str
    state: str = EventDeliveryState.PENDING.value
    execution_id: str = ""
    attempts: int = 0
    error_code: str = ""
    error_message: str = ""
    owner: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        validate_runtime_id(self.event_id, field_name="event_id")
        validate_runtime_id(self.deployment_id, field_name="deployment_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "deployment_id": self.deployment_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "owner": self.owner,
            "state": self.state,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EventDispatchRecord:
        return cls(
            event_id=str(payload.get("event_id") or ""),
            deployment_id=str(payload.get("deployment_id") or ""),
            state=str(payload.get("state") or EventDeliveryState.PENDING.value),
            execution_id=str(payload.get("execution_id") or ""),
            attempts=int(payload.get("attempts") or 0),
            error_code=str(payload.get("error_code") or ""),
            error_message=str(payload.get("error_message") or ""),
            owner=str(payload.get("owner") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


class EventStore(Protocol):
    def append(self, event: EventEnvelope) -> EventEnvelope: ...

    def get(self, event_id: str) -> EventEnvelope | None: ...

    def claim_pending(self, owner: str = "", limit: int = 50) -> tuple[EventEnvelope, ...]: ...

    def get_dispatch_record(self, event_id: str, deployment_id: str) -> EventDispatchRecord | None: ...

    def record_dispatch_started(self, event_id: str, deployment_id: str, owner: str = "") -> EventDispatchRecord: ...

    def mark_dispatched(self, event_id: str, deployment_id: str, execution_id: str) -> EventDispatchRecord: ...

    def mark_failed(self, event_id: str, deployment_id: str, error_code: str, error_message: str = "") -> EventDispatchRecord: ...

    def list_pending_dispatches(self, limit: int = 50) -> tuple[EventDispatchRecord, ...]: ...

    def list_events_by_causation(self, causation_id: str) -> tuple[EventEnvelope, ...]: ...


@dataclass
class InMemoryEventStore:
    events: dict[str, EventEnvelope] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)
    dispatches: dict[tuple[str, str], EventDispatchRecord] = field(default_factory=dict)
    claimed_events: set[str] = field(default_factory=set)

    def append(self, event: EventEnvelope) -> EventEnvelope:
        if event.idempotency_key and event.idempotency_key in self.idempotency_index:
            existing_id = self.idempotency_index[event.idempotency_key]
            return self.events[existing_id]
        if event.event_id in self.events:
            return self.events[event.event_id]

        self.events[event.event_id] = event
        if event.idempotency_key:
            self.idempotency_index[event.idempotency_key] = event.event_id
        return event

    def get(self, event_id: str) -> EventEnvelope | None:
        return self.events.get(event_id)

    def claim_pending(self, owner: str = "", limit: int = 50) -> tuple[EventEnvelope, ...]:
        del owner
        claimed: list[EventEnvelope] = []
        for event_id, event in self.events.items():
            if event_id not in self.claimed_events:
                self.claimed_events.add(event_id)
                claimed.append(event)
                if len(claimed) >= limit:
                    break
        return tuple(claimed)

    def get_dispatch_record(self, event_id: str, deployment_id: str) -> EventDispatchRecord | None:
        return self.dispatches.get((event_id, deployment_id))

    def record_dispatch_started(self, event_id: str, deployment_id: str, owner: str = "") -> EventDispatchRecord:
        key = (event_id, deployment_id)
        existing = self.dispatches.get(key)
        attempts = (existing.attempts if existing else 0) + 1
        record = EventDispatchRecord(
            event_id=event_id,
            deployment_id=deployment_id,
            state=EventDeliveryState.CLAIMED.value,
            attempts=attempts,
            owner=owner or "dispatcher",
            updated_at=utc_now_iso(),
        )
        self.dispatches[key] = record
        return record

    def mark_dispatched(self, event_id: str, deployment_id: str, execution_id: str) -> EventDispatchRecord:
        key = (event_id, deployment_id)
        existing = self.dispatches.get(key)
        attempts = existing.attempts if existing else 1
        record = EventDispatchRecord(
            event_id=event_id,
            deployment_id=deployment_id,
            state=EventDeliveryState.DISPATCHED.value,
            execution_id=execution_id,
            attempts=attempts,
            error_code="",
            error_message="",
            updated_at=utc_now_iso(),
        )
        self.dispatches[key] = record
        return record

    def mark_failed(self, event_id: str, deployment_id: str, error_code: str, error_message: str = "") -> EventDispatchRecord:
        key = (event_id, deployment_id)
        existing = self.dispatches.get(key)
        attempts = existing.attempts if existing else 1
        record = EventDispatchRecord(
            event_id=event_id,
            deployment_id=deployment_id,
            state=EventDeliveryState.FAILED.value,
            attempts=attempts,
            error_code=error_code,
            error_message=error_message,
            updated_at=utc_now_iso(),
        )
        self.dispatches[key] = record
        return record

    def list_pending_dispatches(self, limit: int = 50) -> tuple[EventDispatchRecord, ...]:
        results: list[EventDispatchRecord] = []
        for record in self.dispatches.values():
            if record.state in {EventDeliveryState.PENDING.value, EventDeliveryState.CLAIMED.value, EventDeliveryState.FAILED.value}:
                results.append(record)
                if len(results) >= limit:
                    break
        return tuple(results)

    def list_events_by_causation(self, causation_id: str) -> tuple[EventEnvelope, ...]:
        return tuple(event for event in self.events.values() if event.causation_id == causation_id)


class SqliteEventStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    event_type TEXT NOT NULL,
                    causation_id TEXT NOT NULL DEFAULT '',
                    correlation_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    claimed INTEGER NOT NULL DEFAULT 0,
                    owner TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_events_causation ON runtime_events(causation_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON runtime_events(event_type)")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_event_dispatches (
                    event_id TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    execution_id TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (event_id, deployment_id)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_dispatches_state ON runtime_event_dispatches(state)")
            connection.commit()

    def append(self, event: EventEnvelope) -> EventEnvelope:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if event.idempotency_key:
                row = connection.execute(
                    "SELECT payload_json FROM runtime_events WHERE idempotency_key=?", (event.idempotency_key,)
                ).fetchone()
                if row:
                    connection.commit()
                    return EventEnvelope.from_json(row["payload_json"])

            row = connection.execute(
                "SELECT payload_json FROM runtime_events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if row:
                connection.commit()
                return EventEnvelope.from_json(row["payload_json"])

            connection.execute(
                """
                INSERT INTO runtime_events
                (event_id, idempotency_key, event_type, causation_id, correlation_id, trace_id, payload_json, claimed, owner, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)
                """,
                (
                    event.event_id,
                    event.idempotency_key or None,
                    event.event_type,
                    event.causation_id,
                    event.correlation_id,
                    event.trace_id,
                    event.to_json(),
                    event.occurred_at or utc_now_iso(),
                    utc_now_iso(),
                ),
            )
            connection.commit()
        return event

    def get(self, event_id: str) -> EventEnvelope | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM runtime_events WHERE event_id=?", (event_id,)).fetchone()
        return EventEnvelope.from_json(row["payload_json"]) if row else None

    def claim_pending(self, owner: str = "", limit: int = 50) -> tuple[EventEnvelope, ...]:
        owner = owner or "dispatcher"
        claimed_events: list[EventEnvelope] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT event_id, payload_json FROM runtime_events WHERE claimed=0 ORDER BY rowid ASC LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE runtime_events SET claimed=1, owner=?, updated_at=? WHERE event_id=?",
                    (owner, utc_now_iso(), row["event_id"]),
                )
                claimed_events.append(EventEnvelope.from_json(row["payload_json"]))
            connection.commit()
        return tuple(claimed_events)

    def get_dispatch_record(self, event_id: str, deployment_id: str) -> EventDispatchRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_event_dispatches WHERE event_id=? AND deployment_id=?",
                (event_id, deployment_id),
            ).fetchone()
        return EventDispatchRecord.from_dict(dict(row)) if row else None

    def record_dispatch_started(self, event_id: str, deployment_id: str, owner: str = "") -> EventDispatchRecord:
        owner = owner or "dispatcher"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempts FROM runtime_event_dispatches WHERE event_id=? AND deployment_id=?",
                (event_id, deployment_id),
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            connection.execute(
                """
                INSERT INTO runtime_event_dispatches
                (event_id, deployment_id, state, execution_id, attempts, error_code, error_message, owner, updated_at)
                VALUES (?, ?, ?, '', ?, '', '', ?, ?)
                ON CONFLICT(event_id, deployment_id) DO UPDATE SET
                    state=excluded.state,
                    attempts=excluded.attempts,
                    owner=excluded.owner,
                    updated_at=excluded.updated_at
                """,
                (
                    event_id,
                    deployment_id,
                    EventDeliveryState.CLAIMED.value,
                    attempts,
                    owner,
                    utc_now_iso(),
                ),
            )
            connection.commit()
        return self.get_dispatch_record(event_id, deployment_id)  # type: ignore[return-value]

    def mark_dispatched(self, event_id: str, deployment_id: str, execution_id: str) -> EventDispatchRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE runtime_event_dispatches
                SET state=?, execution_id=?, error_code='', error_message='', owner='', updated_at=?
                WHERE event_id=? AND deployment_id=?
                """,
                (
                    EventDeliveryState.DISPATCHED.value,
                    execution_id,
                    utc_now_iso(),
                    event_id,
                    deployment_id,
                ),
            )
            connection.commit()
        return self.get_dispatch_record(event_id, deployment_id)  # type: ignore[return-value]

    def mark_failed(self, event_id: str, deployment_id: str, error_code: str, error_message: str = "") -> EventDispatchRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempts FROM runtime_event_dispatches WHERE event_id=? AND deployment_id=?",
                (event_id, deployment_id),
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            connection.execute(
                """
                INSERT INTO runtime_event_dispatches
                (event_id, deployment_id, state, execution_id, attempts, error_code, error_message, owner, updated_at)
                VALUES (?, ?, ?, '', ?, ?, ?, '', ?)
                ON CONFLICT(event_id, deployment_id) DO UPDATE SET
                    state=excluded.state,
                    error_code=excluded.error_code,
                    error_message=excluded.error_message,
                    owner='',
                    updated_at=excluded.updated_at
                """,
                (
                    event_id,
                    deployment_id,
                    EventDeliveryState.FAILED.value,
                    attempts,
                    error_code,
                    error_message,
                    utc_now_iso(),
                ),
            )
            connection.commit()
        return self.get_dispatch_record(event_id, deployment_id)  # type: ignore[return-value]

    def list_pending_dispatches(self, limit: int = 50) -> tuple[EventDispatchRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runtime_event_dispatches
                WHERE state IN (?, ?, ?)
                ORDER BY updated_at ASC LIMIT ?
                """,
                (
                    EventDeliveryState.PENDING.value,
                    EventDeliveryState.CLAIMED.value,
                    EventDeliveryState.FAILED.value,
                    limit,
                ),
            ).fetchall()
        return tuple(EventDispatchRecord.from_dict(dict(row)) for row in rows)

    def list_events_by_causation(self, causation_id: str) -> tuple[EventEnvelope, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_events WHERE causation_id=?", (causation_id,)
            ).fetchall()
        return tuple(EventEnvelope.from_json(row["payload_json"]) for row in rows)
