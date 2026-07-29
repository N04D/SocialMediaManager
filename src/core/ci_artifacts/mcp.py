"""MCP-style query helpers for CI artifact imports."""

from __future__ import annotations

from .operator_flow import CiEvidenceOperatorService
from .service import CiArtifactImportService


class CiArtifactMCP:
    def __init__(self, service: CiArtifactImportService | None = None) -> None:
        self.service = service or CiArtifactImportService()
        self.operator = CiEvidenceOperatorService(import_service=self.service)

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

    def get_github_ci_operator_status(self) -> dict:
        return self.operator.status()

    def get_github_ci_current_commit(self) -> dict:
        return self.operator.current_commit()

    def get_github_ci_matching_runs(self, origin_id: str, commit_sha: str = "") -> dict:
        return self.operator.discover_runs(origin_id, commit_sha=commit_sha)

    def get_github_ci_run_attempts(self, origin_id: str, run_id: str) -> dict:
        attempts = [item for item in self.service.list_runs(origin_id)["runs"] if item.get("run_id") == run_id]
        return {"run_id": run_id, "attempts": attempts}

    def get_github_ci_artifacts(self, origin_id: str, run_id: str, run_attempt: int = 1) -> dict:
        return self.service.artifacts(origin_id, run_id, run_attempt)

    def get_github_ci_import_dry_run(self, dry_run_id: str) -> dict:
        return {"dry_run": self.service.repository.get_dry_run(dry_run_id)}

    def get_github_ci_import_timeline(self, import_id: str) -> dict:
        return self.operator.import_timeline(import_id)

    def get_github_ci_evidence_review(self, import_id: str) -> dict:
        show = self.service.import_show(import_id)
        return {
            "import_request": show["import_request"],
            "awaiting_review": show["import_request"]["status"] == "awaiting_review",
        }

    def get_github_ci_evidence_promotion(self, import_id: str) -> dict:
        attestations = self.service.import_show(import_id)["attestations"]
        promotions = [
            item
            for item in self.service.repository.promotions()
            if attestations and item.get("import_attestation_id") == attestations[0].get("id")
        ]
        return {"promotions": promotions}

    def explain_github_ci_readiness(self) -> dict:
        return self.operator.readiness()


__all__ = ["CiArtifactMCP"]
