"""Bounded CI artifact import worker."""

from __future__ import annotations

from .service import CiArtifactImportService


class CiArtifactImportWorker:
    worker_execution_model = "thread"

    def __init__(self, service: CiArtifactImportService, *, worker_id: str = "ci-import-worker-1") -> None:
        self.service = service
        self.worker_id = worker_id

    def run_once(self, *, signer_id: str = "") -> dict:
        request = self.service.repository.claim_next(worker_id=self.worker_id, lease_seconds=60)
        if request is None:
            return {"claimed": 0, "processed": 0}
        result = self.service.process_import(request["id"], signer_id=signer_id)
        return {"claimed": 1, "processed": 1, "result": result}


__all__ = ["CiArtifactImportWorker"]
