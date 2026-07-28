"""GitHub Actions origin models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubActionsOriginReference:
    id: str
    workspace_id_or_host_scope: str
    api_origin_reference_id: str
    repository_owner: str
    repository_name: str
    repository_id: str
    workflow_identity: str
    allowed_workflow_paths: tuple[str, ...]
    allowed_branches: tuple[str, ...]
    allowed_events: tuple[str, ...]
    allowed_artifact_name_patterns: tuple[str, ...]
    credential_secret_reference: str
    require_success_conclusion: bool
    allow_pull_request_runs: bool
    allow_fork_runs: bool
    enabled: bool
    created_at: str
    updated_at: str
    version: int
    provider_id: str = "ci.github_actions"


__all__ = ["GitHubActionsOriginReference"]
