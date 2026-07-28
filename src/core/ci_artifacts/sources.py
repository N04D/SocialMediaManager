"""Provider-neutral CI artifact source protocol."""

from __future__ import annotations

from typing import Protocol

from .models import CiWorkflowArtifact, CiWorkflowRun


class CiArtifactSource(Protocol):
    source_id: str
    source_version: str

    def validate_origin(self, origin_reference_id: str) -> dict: ...

    def list_matching_runs(
        self, origin_reference_id: str, *, commit_sha: str = "", branch: str = "", workflow_identity: str = ""
    ) -> list[CiWorkflowRun]: ...

    def get_run(self, origin_reference_id: str, run_id: str, run_attempt: int) -> CiWorkflowRun: ...

    def list_run_artifacts(
        self, origin_reference_id: str, run_id: str, run_attempt: int
    ) -> list[CiWorkflowArtifact]: ...

    def download_artifact(self, origin_reference_id: str, artifact_id: str) -> bytes: ...

    def get_health(self, origin_reference_id: str) -> dict: ...


__all__ = ["CiArtifactSource"]
