from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .events import EventEnvelope, EventSource, utc_now_iso
from .event_store import SqliteEventStore
from .installs import Install


@dataclass(frozen=True)
class ExternalSourceRecord:
    external_event_id: str
    event_type: str
    occurred_at: str
    payload: dict[str, Any]
    resource_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceBatch:
    records: tuple[ExternalSourceRecord, ...]
    next_checkpoint: str
    has_more: bool = False
    gap_detected: bool = False


@dataclass(frozen=True)
class SourceCheckpoint:
    source_id: str
    install_id: str
    cursor: str
    updated_at: str


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    install_id: str
    last_poll_at: str
    last_success_at: str
    checkpoint: str
    last_error: str
    consecutive_failures: int


class ExternalEventSource(Protocol):
    source_id: str

    def poll(self, *, install_id: str, checkpoint: str = "", limit: int = 10) -> SourceBatch:
        ...


class SourceCheckpointStore:
    """SQLite-backed persistent store for source checkpoints, worker leases, and health tracking."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_checkpoints (
                    source_id TEXT NOT NULL,
                    install_id TEXT NOT NULL,
                    cursor TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, install_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_leases (
                    source_id TEXT NOT NULL,
                    install_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, install_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_health (
                    source_id TEXT NOT NULL,
                    install_id TEXT NOT NULL,
                    last_poll_at TEXT NOT NULL,
                    last_success_at TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    last_error TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (source_id, install_id)
                )
                """
            )
            conn.commit()

    def get_checkpoint(self, source_id: str, install_id: str) -> SourceCheckpoint | None:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT source_id, install_id, cursor, updated_at
                FROM source_checkpoints
                WHERE source_id = ? AND install_id = ?
                """,
                (source_id, install_id),
            ).fetchone()
            if row is None:
                return None
            return SourceCheckpoint(
                source_id=row["source_id"],
                install_id=row["install_id"],
                cursor=row["cursor"],
                updated_at=row["updated_at"],
            )

    def advance_checkpoint(self, source_id: str, install_id: str, cursor: str) -> SourceCheckpoint:
        now = utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO source_checkpoints (source_id, install_id, cursor, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id, install_id) DO UPDATE SET
                    cursor = excluded.cursor,
                    updated_at = excluded.updated_at
                """,
                (source_id, install_id, cursor, now),
            )
            conn.commit()
        return SourceCheckpoint(
            source_id=source_id,
            install_id=install_id,
            cursor=cursor,
            updated_at=now,
        )

    def acquire_lease(
        self, source_id: str, install_id: str, worker_id: str, lease_duration_sec: float = 30.0
    ) -> bool:
        now_dt = datetime.now(timezone.utc)
        expires_dt = datetime.fromtimestamp(now_dt.timestamp() + lease_duration_sec, tz=timezone.utc)
        now_iso = now_dt.isoformat()
        expires_iso = expires_dt.isoformat()

        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT worker_id, expires_at
                FROM source_leases
                WHERE source_id = ? AND install_id = ?
                """,
                (source_id, install_id),
            ).fetchone()

            if row is not None:
                existing_worker = row["worker_id"]
                expires_at = row["expires_at"]
                if existing_worker != worker_id and expires_at > now_iso:
                    return False

            conn.execute(
                """
                INSERT INTO source_leases (source_id, install_id, worker_id, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id, install_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    expires_at = excluded.expires_at
                """,
                (source_id, install_id, worker_id, expires_iso),
            )
            conn.commit()
            return True

    def release_lease(self, source_id: str, install_id: str, worker_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                DELETE FROM source_leases
                WHERE source_id = ? AND install_id = ? AND worker_id = ?
                """,
                (source_id, install_id, worker_id),
            )
            conn.commit()

    def record_health(
        self, source_id: str, install_id: str, *, success: bool, error: str = "", checkpoint: str = ""
    ) -> SourceHealth:
        now = utc_now_iso()
        with self._get_connection() as conn:
            existing = conn.execute(
                """
                SELECT last_success_at, consecutive_failures, checkpoint
                FROM source_health
                WHERE source_id = ? AND install_id = ?
                """,
                (source_id, install_id),
            ).fetchone()

            last_success = existing["last_success_at"] if existing else ""
            current_checkpoint = checkpoint or (existing["checkpoint"] if existing else "")
            failures = existing["consecutive_failures"] if existing else 0

            if success:
                last_success = now
                failures = 0
                last_error = ""
            else:
                failures += 1
                last_error = error

            conn.execute(
                """
                INSERT INTO source_health (source_id, install_id, last_poll_at, last_success_at, checkpoint, last_error, consecutive_failures)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, install_id) DO UPDATE SET
                    last_poll_at = excluded.last_poll_at,
                    last_success_at = excluded.last_success_at,
                    checkpoint = excluded.checkpoint,
                    last_error = excluded.last_error,
                    consecutive_failures = excluded.consecutive_failures
                """,
                (source_id, install_id, now, last_success, current_checkpoint, last_error, failures),
            )
            conn.commit()

        return SourceHealth(
            source_id=source_id,
            install_id=install_id,
            last_poll_at=now,
            last_success_at=last_success,
            checkpoint=current_checkpoint,
            last_error=last_error if not success else "",
            consecutive_failures=failures if not success else 0,
        )

    def get_health(self, source_id: str, install_id: str) -> SourceHealth:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT source_id, install_id, last_poll_at, last_success_at, checkpoint, last_error, consecutive_failures
                FROM source_health
                WHERE source_id = ? AND install_id = ?
                """,
                (source_id, install_id),
            ).fetchone()

            if row is None:
                return SourceHealth(
                    source_id=source_id,
                    install_id=install_id,
                    last_poll_at="",
                    last_success_at="",
                    checkpoint="",
                    last_error="",
                    consecutive_failures=0,
                )

            return SourceHealth(
                source_id=row["source_id"],
                install_id=row["install_id"],
                last_poll_at=row["last_poll_at"],
                last_success_at=row["last_success_at"],
                checkpoint=row["checkpoint"],
                last_error=row["last_error"],
                consecutive_failures=row["consecutive_failures"],
            )


def poll_and_ingest_external_events(
    *,
    source: ExternalEventSource,
    install: Install,
    event_store: SqliteEventStore,
    checkpoint_store: SourceCheckpointStore,
    limit: int = 10,
    worker_id: str = "default-worker",
    first_poll_policy: str = "FROM_NOW",
) -> tuple[bool, str, list[EventEnvelope]]:
    """Poll external event source, persist normalized events, and advance checkpoint safely."""

    source_id = source.source_id
    install_id = install.install_id

    # 1. Acquire worker lease
    acquired = checkpoint_store.acquire_lease(source_id, install_id, worker_id=worker_id)
    if not acquired:
        return False, "LEASE_BUSY", []

    try:
        # 2. Get current checkpoint
        current_cp = checkpoint_store.get_checkpoint(source_id, install_id)
        is_first_poll = current_cp is None
        cursor = current_cp.cursor if current_cp else ""

        # 3. Handle First-Poll Bootstrap (FROM_NOW policy)
        if is_first_poll and first_poll_policy == "FROM_NOW":
            try:
                batch = source.poll(install_id=install_id, checkpoint="", limit=limit)
            except Exception as exc:
                checkpoint_store.record_health(source_id, install_id, success=False, error=str(exc))
                return False, f"POLL_FAILED: {exc}", []

            checkpoint_store.advance_checkpoint(source_id, install_id, batch.next_checkpoint)
            checkpoint_store.record_health(
                source_id, install_id, success=True, checkpoint=batch.next_checkpoint
            )
            return True, "BOOTSTRAP_FROM_NOW", []

        # 4. Perform Remote Source Poll
        try:
            batch = source.poll(install_id=install_id, checkpoint=cursor, limit=limit)
        except Exception as exc:
            checkpoint_store.record_health(source_id, install_id, success=False, error=str(exc))
            return False, f"POLL_FAILED: {exc}", []

        if getattr(batch, "gap_detected", False):
            checkpoint_store.record_health(source_id, install_id, success=False, error="SOURCE_GAP_DETECTED")
            return False, "SOURCE_GAP_DETECTED", []

        # 5. Normalize Records -> EventEnvelope instances
        ingested_events: list[EventEnvelope] = []
        for rec in batch.records:
            event_id = f"evt_ext_{source_id}_{rec.external_event_id}"
            envelope = EventEnvelope(
                event_id=event_id,
                event_type=rec.event_type,
                source=EventSource(component=source_id, provider=install.provider, install=install.install_id),
                payload=rec.payload,
                entity_ref=rec.resource_ref,
                external_event_id=rec.external_event_id,
                occurred_at=rec.occurred_at,
                received_at=utc_now_iso(),
                causation_id=rec.external_event_id,
                correlation_id=f"corr_ext_{rec.external_event_id}",
            )

            # Persist & Deduplicate in SqliteEventStore
            try:
                event_store.append(envelope)
                ingested_events.append(envelope)
            except Exception:
                # Deduplicated if already present in SqliteEventStore
                pass

        # 6. Advance Checkpoint ONLY AFTER event persistence succeeds
        checkpoint_store.advance_checkpoint(source_id, install_id, batch.next_checkpoint)
        checkpoint_store.record_health(source_id, install_id, success=True, checkpoint=batch.next_checkpoint)

        return True, "OK", ingested_events

    finally:
        checkpoint_store.release_lease(source_id, install_id, worker_id=worker_id)
