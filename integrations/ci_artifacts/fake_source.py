"""Deterministic GitHub Actions source fixtures."""

from __future__ import annotations

from src.core.certification_evidence.models import stable_checksum, utc_now_iso
from src.core.ci_artifacts.models import CiWorkflowArtifact, CiWorkflowRun
from src.providers.ci.github_actions.origins import default_github_origin_payload
from src.providers.ci.github_actions.source import GitHubActionsArtifactSource, SecretReader


def fake_github_source(
    package_bytes: bytes, *, commit_sha: str, secret_reader: SecretReader | None = None
) -> GitHubActionsArtifactSource:
    origin = default_github_origin_payload()
    origin_id = origin["id"]
    run = CiWorkflowRun(
        source_id="ci.github_actions",
        origin_reference_id=origin_id,
        repository_identity=f"{origin['repository_owner']}/{origin['repository_name']}",
        workflow_identity=origin["workflow_identity"],
        run_id="1001",
        run_attempt=1,
        event="push",
        status="completed",
        conclusion="success",
        head_sha=commit_sha,
        head_branch="main",
        actor_reference="actor:100",
        triggering_actor_reference="actor:100",
        created_at=utc_now_iso(),
        started_at=utc_now_iso(),
        completed_at=utc_now_iso(),
        provider_url_reference="github-run:1001",
    )
    artifact = CiWorkflowArtifact(
        source_id="ci.github_actions",
        origin_reference_id=origin_id,
        run_id=run.run_id,
        run_attempt=1,
        artifact_id="5001",
        artifact_name="owned-publication-certification-evidence",
        size_bytes=len(package_bytes),
        provider_digest="sha256:" + stable_checksum(package_bytes.decode("latin1")),
        created_at=utc_now_iso(),
        expires_at="2026-12-31T00:00:00Z",
        expired=False,
        archive_reference="github-artifact:5001",
    )
    return GitHubActionsArtifactSource(
        origins={origin_id: origin},
        runs={(origin_id, run.run_id, 1): run},
        artifacts={(origin_id, run.run_id, 1): [artifact]},
        archives={artifact.artifact_id: package_bytes},
        secret_reader=secret_reader,
    )


def source_with_duplicate_artifact_name(package_bytes: bytes, *, commit_sha: str) -> GitHubActionsArtifactSource:
    source = fake_github_source(package_bytes, commit_sha=commit_sha)
    origin_id = "github-actions-owned-publication"
    first = source._artifacts[(origin_id, "1001", 1)][0]
    duplicate = CiWorkflowArtifact(
        **{**first.__dict__, "artifact_id": "5002", "provider_digest": first.provider_digest}
    )
    source._artifacts[(origin_id, "1001", 1)] = [first, duplicate]
    source.archives["5002"] = package_bytes
    return source


__all__ = ["fake_github_source", "source_with_duplicate_artifact_name"]
