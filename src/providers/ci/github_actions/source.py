"""First-party read-only GitHub Actions artifact source."""

from __future__ import annotations

from src.core.ci_artifacts.contracts import GITHUB_ACTIONS_ARTIFACT_SOURCE_VERSION
from src.core.ci_artifacts.errors import CiArtifactError
from src.core.ci_artifacts.models import CiWorkflowArtifact, CiWorkflowRun
from src.core.ci_artifacts.sources import CiArtifactSource


class GitHubActionsArtifactSource(CiArtifactSource):
    source_id = "ci.github_actions"
    source_version = GITHUB_ACTIONS_ARTIFACT_SOURCE_VERSION
    data_access = "read_only"
    execution_mode = "built_in_in_process"

    def __init__(
        self,
        *,
        origins: dict[str, dict],
        runs: dict[tuple[str, str, int], CiWorkflowRun],
        artifacts: dict[tuple[str, str, int], list[CiWorkflowArtifact]],
        archives: dict[str, bytes],
    ) -> None:
        self.origins = origins
        self.runs = runs
        self._artifacts = artifacts
        self.archives = archives
        self.write_operations: list[str] = []

    def validate_origin(self, origin_reference_id: str) -> dict:
        origin = self._origin(origin_reference_id)
        return {
            "origin_id": origin_reference_id,
            "provider_id": self.source_id,
            "read_only": True,
            "repository": f"{origin['repository_owner']}/{origin['repository_name']}",
            "workflow_identity": origin["workflow_identity"],
            "valid": True,
        }

    def list_matching_runs(
        self, origin_reference_id: str, *, commit_sha: str = "", branch: str = "", workflow_identity: str = ""
    ) -> list[CiWorkflowRun]:
        self._origin(origin_reference_id)
        runs = [run for (origin_id, _, _), run in self.runs.items() if origin_id == origin_reference_id]
        if commit_sha:
            runs = [run for run in runs if run.head_sha == commit_sha]
        if branch:
            runs = [run for run in runs if run.head_branch == branch]
        if workflow_identity:
            runs = [run for run in runs if run.workflow_identity == workflow_identity]
        return sorted(runs, key=lambda item: (item.run_id, item.run_attempt))

    def get_run(self, origin_reference_id: str, run_id: str, run_attempt: int) -> CiWorkflowRun:
        self._origin(origin_reference_id)
        try:
            return self.runs[(origin_reference_id, run_id, run_attempt)]
        except KeyError as exc:
            raise CiArtifactError("ci.run_not_found", "Workflow run was not found.") from exc

    def list_run_artifacts(self, origin_reference_id: str, run_id: str, run_attempt: int) -> list[CiWorkflowArtifact]:
        self.get_run(origin_reference_id, run_id, run_attempt)
        return list(self._artifacts.get((origin_reference_id, run_id, run_attempt), ()))

    def download_artifact(self, origin_reference_id: str, artifact_id: str) -> bytes:
        self._origin(origin_reference_id)
        if artifact_id not in self.archives:
            raise CiArtifactError("ci.artifact_archive_missing", "Artifact archive is unavailable.")
        return self.archives[artifact_id]

    def get_health(self, origin_reference_id: str) -> dict:
        self._origin(origin_reference_id)
        return {
            "source_id": self.source_id,
            "authentication": "PASS",
            "repository_access": "PASS",
            "artifact_listing_access": "PASS",
            "rate_limit": "ok",
            "read_only": True,
            "write_operations": self.write_operations,
        }

    def _origin(self, origin_reference_id: str) -> dict:
        if origin_reference_id not in self.origins:
            raise CiArtifactError("ci.origin_not_found", "GitHub Actions origin is not registered.")
        origin = self.origins[origin_reference_id]
        if not origin.get("enabled", True):
            raise CiArtifactError("ci.origin_disabled", "GitHub Actions origin is disabled.")
        return origin


__all__ = ["GitHubActionsArtifactSource"]
