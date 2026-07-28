"""MCP-style query helpers for CI artifact imports."""

from __future__ import annotations

from .service import CiArtifactImportService


class CiArtifactMCP:
    def __init__(self, service: CiArtifactImportService | None = None) -> None:
        self.service = service or CiArtifactImportService()

    def get_ci_artifact_origins(self) -> dict:
        return self.service.origins()

    def get_ci_workflow_runs(self, origin_id: str, commit_sha: str = "") -> dict:
        return self.service.list_runs(origin_id, commit_sha=commit_sha)

    def get_ci_run_artifacts(self, origin_id: str, run_id: str) -> dict:
        return self.service.artifacts(origin_id, run_id)

    def get_ci_artifact_import(self, import_id: str) -> dict:
        return self.service.import_show(import_id)

    def get_ci_import_attestation(self, import_id: str) -> dict:
        return {"attestations": self.service.import_show(import_id)["attestations"]}

    def explain_ci_artifact_trust(self, import_id: str) -> dict:
        return self.service.import_show(import_id)

    def explain_ci_import_failure(self, import_id: str) -> dict:
        return self.service.reconcile(import_id)

    def compare_local_and_ci_evidence(self) -> dict:
        return self.service.readiness()


__all__ = ["CiArtifactMCP"]
