"""Read-only instrumentation verification worker."""

from __future__ import annotations

from dataclasses import dataclass, field

from .service import WebsiteInstrumentationService


@dataclass
class WebsiteInstrumentationVerificationWorker:
    service: WebsiteInstrumentationService
    worker_id: str = "website-instrumentation-verifier"
    batch_size: int = 5
    heartbeat_count: int = 0
    processed: int = 0
    last_status: str = "idle"
    errors: list[str] = field(default_factory=list)

    def heartbeat(self) -> None:
        self.heartbeat_count += 1

    def run_once(self) -> dict[str, object]:
        self.heartbeat()
        configs = self.service.list_configs()["configs"][: self.batch_size]
        for config in configs:
            try:
                self.service.verify(str(config["id"]))
                self.processed += 1
            except Exception as exc:
                self.errors.append(type(exc).__name__)
        self.last_status = "completed" if not self.errors else "completed_with_warnings"
        return {
            "worker_id": self.worker_id,
            "worker_type": "WebsiteInstrumentationVerificationWorker",
            "heartbeat_count": self.heartbeat_count,
            "processed": self.processed,
            "errors": tuple(self.errors),
            "backend_provider_writes": 0,
            "bounded_batch": self.batch_size,
            "status": self.last_status,
        }


__all__ = ["WebsiteInstrumentationVerificationWorker"]
