"""Bounded staging analytics certification worker."""

from __future__ import annotations

from dataclasses import dataclass

from .service import StagingAnalyticsCertificationService


@dataclass
class StagingAnalyticsCertificationWorker:
    service: StagingAnalyticsCertificationService
    worker_id: str = "staging-analytics-certifier"
    batch_size: int = 1
    heartbeat_count: int = 0
    processed: int = 0

    def run_once(self) -> dict[str, object]:
        self.heartbeat_count += 1
        profiles = self.service.list_profiles()["profiles"][: self.batch_size]
        for profile in profiles:
            self.service.deterministic_certification(str(profile["id"]))
            self.processed += 1
        return {
            "worker_id": self.worker_id,
            "heartbeat_count": self.heartbeat_count,
            "processed": self.processed,
            "bounded_batch": self.batch_size,
            "backend_provider_writes": 0,
        }


__all__ = ["StagingAnalyticsCertificationWorker"]
