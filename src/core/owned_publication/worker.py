"""Bounded owned-publication operations worker."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import ExecutionTimelineEvent, stable_checksum
from .persistence import DatabaseOwnedPublicationRepository


def _lease_deadline(seconds: float = 30) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(seconds, 0.1))).isoformat().replace("+00:00", "Z")


@dataclass
class OwnedPublicationWorkerStats:
    worker_id: str
    occurrence_claims: int = 0
    reconciliation_claims: int = 0
    heartbeats: int = 0
    processed: int = 0
    duplicate_mutations: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class OwnedPublicationOperationsWorker:
    """Small host-owned worker loop using the production repository claims."""

    execution_model = "thread"

    def __init__(
        self,
        repository: DatabaseOwnedPublicationRepository,
        *,
        worker_id: str,
        batch_size: int = 2,
        poll_interval: float = 0.05,
        lease_seconds: float = 1.0,
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.batch_size = max(1, batch_size)
        self.poll_interval = max(0.01, poll_interval)
        self.lease_seconds = max(0.1, lease_seconds)
        self.stop_event = threading.Event()
        self.stats = OwnedPublicationWorkerStats(worker_id)

    def run_once(self) -> OwnedPublicationWorkerStats:
        self.repository.recovery()
        self._process_occurrences()
        self._process_reconciliation()
        return self.stats

    def run_until_idle(self, *, max_polls: int = 20) -> OwnedPublicationWorkerStats:
        idle_polls = 0
        for _ in range(max_polls):
            before = self.stats.processed
            self.run_once()
            if self.stats.processed == before:
                idle_polls += 1
                if idle_polls >= 2:
                    break
            else:
                idle_polls = 0
            if self.stop_event.wait(self.poll_interval):
                break
        return self.stats

    def stop(self) -> None:
        self.stop_event.set()

    def _record(self, event_type: str, **payload: Any) -> None:
        safe = {key: value for key, value in payload.items() if key not in {"body", "token", "authorization"}}
        self.stats.events.append({"event": event_type, "worker_id": self.worker_id, **safe})

    def _process_occurrences(self) -> None:
        for occurrence_id in self.repository.list_occurrence_ids(limit=self.batch_size):
            if not self.repository.claim_occurrence(occurrence_id, self.worker_id, _lease_deadline(self.lease_seconds)):
                continue
            self.stats.occurrence_claims += 1
            self._record("worker claim", kind="occurrence", item_id=occurrence_id)
            self.repository.append_execution_event(
                "workspace-1",
                f"attempt-{occurrence_id}",
                occurrence_id,
                ExecutionTimelineEvent(
                    datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "Dependency reevaluated",
                    "OwnedPublicationOperationsWorker",
                    "pre_mutation",
                    "waiting_dependency",
                    "No mutation executed by certification worker.",
                ),
                idempotency_key="worker-occurrence-" + stable_checksum(occurrence_id)[:12],
            )
            self.stats.processed += 1

    def _process_reconciliation(self) -> None:
        for item_id in self.repository.list_reconciliation_ids(limit=self.batch_size):
            lease = self.repository.claim_reconciliation(item_id, self.worker_id, _lease_deadline(self.lease_seconds))
            if lease.status != "claimed":
                continue
            self.stats.reconciliation_claims += 1
            self._record("worker claim", kind="reconciliation", item_id=item_id)
            if self.repository.heartbeat_reconciliation(item_id, self.worker_id, _lease_deadline(self.lease_seconds)):
                self.stats.heartbeats += 1
                self._record("heartbeat", item_id=item_id)
            self.repository.resolve_claimed_reconciliation(item_id, self.worker_id, "read-only certification check")
            self.stats.processed += 1


def run_worker_thread(worker: OwnedPublicationOperationsWorker) -> threading.Thread:
    thread = threading.Thread(target=worker.run_until_idle, name=worker.worker_id)
    thread.start()
    return thread


__all__ = ["OwnedPublicationOperationsWorker", "OwnedPublicationWorkerStats", "run_worker_thread"]
