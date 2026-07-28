"""Host-owned GitHub Actions origin fixtures."""

from __future__ import annotations

from dataclasses import asdict

from src.core.certification_evidence.models import utc_now_iso

from .models import GitHubActionsOriginReference


def default_github_origin() -> GitHubActionsOriginReference:
    now = utc_now_iso()
    return GitHubActionsOriginReference(
        id="github-actions-owned-publication",
        workspace_id_or_host_scope="host",
        api_origin_reference_id="github-api",
        repository_owner="example",
        repository_name="SocialMediaManager",
        repository_id="repo-123",
        workflow_identity="Owned Publication Operations",
        allowed_workflow_paths=(".github/workflows/owned-publication-operations.yml",),
        allowed_branches=("main",),
        allowed_events=("push", "workflow_dispatch", "schedule"),
        allowed_artifact_name_patterns=("owned-publication-certification-evidence",),
        credential_secret_reference="secretref:github/actions-read",
        require_success_conclusion=True,
        allow_pull_request_runs=False,
        allow_fork_runs=False,
        enabled=True,
        created_at=now,
        updated_at=now,
        version=1,
    )


def default_github_origin_payload() -> dict:
    return asdict(default_github_origin())


__all__ = ["default_github_origin", "default_github_origin_payload"]
