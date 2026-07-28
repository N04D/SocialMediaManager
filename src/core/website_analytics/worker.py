"""Bounded website analytics sync worker."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .service import WebsiteAnalyticsService


def _lease_deadline(seconds: float = 30) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(seconds, 0.1))).isoformat().replace("+00:00", "Z")


@dataclass
class WebsiteAnalyticsWorkerStats:
    worker_id: str
    claimed: int = 0
    heartbeats: int = 0
    completed: int = 0
    failed: int = 0


class WebsiteAnalyticsSyncWorker:
    execution_model = "thread"

    def __init__(self, service: WebsiteAnalyticsService, *, worker_id: str, batch_size: int = 2) -> None:
        self.service = service
        self.worker_id = worker_id
        self.batch_size = max(1, batch_size)
        self.stop_event = threading.Event()
        self.stats = WebsiteAnalyticsWorkerStats(worker_id)

    def run_once(self) -> WebsiteAnalyticsWorkerStats:
        for state in self.service.repository.list_sync_states(claimable=True, limit=self.batch_size):
            if self.stop_event.is_set():
                break
            if not self.service.repository.claim_sync_state(state.id, self.worker_id, _lease_deadline()):
                continue
            self.stats.claimed += 1
            if self.service.repository.heartbeat_sync_state(state.id, self.worker_id, _lease_deadline()):
                self.stats.heartbeats += 1
            try:
                self.service.sync(state.account_id, worker_id=self.worker_id, claim=False)
                self.stats.completed += 1
            except Exception:
                self.stats.failed += 1
        return self.stats

    def stop(self) -> None:
        self.stop_event.set()


__all__ = ["WebsiteAnalyticsSyncWorker", "WebsiteAnalyticsWorkerStats"]
