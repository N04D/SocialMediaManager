"""Provider-neutral CI artifact import models."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.certification_evidence.models import CertificationSignatureEnvelope, utc_now_iso


@dataclass(frozen=True)
class CiWorkflowRun:
    source_id: str
    origin_reference_id: str
    repository_identity: str
    workflow_identity: str
    run_id: str
    run_attempt: int
    event: str
    status: str
    conclusion: str
    head_sha: str
    head_branch: str
    actor_reference: str
    triggering_actor_reference: str
    created_at: str
    started_at: str
    completed_at: str
    provider_url_reference: str
    fork: bool = False


@dataclass(frozen=True)
class CiWorkflowArtifact:
    source_id: str
    origin_reference_id: str
    run_id: str
    run_attempt: int
    artifact_id: str
    artifact_name: str
    size_bytes: int
    provider_digest: str
    created_at: str
    expires_at: str
    expired: bool
    archive_reference: str


@dataclass(frozen=True)
class CiArtifactImportRequest:
    id: str
    workspace_id: str
    origin_reference_id: str
    workflow_run_id: str
    run_attempt: int
    artifact_id: str
    expected_commit_sha: str
    expected_evidence_types: tuple[str, ...]
    requested_by: str
    status: str
    created_at: str
    version: int = 1
    lease_owner: str = ""
    lease_expires_at: str = ""


@dataclass(frozen=True)
class CiArtifactImportAttestation:
    id: str
    workspace_id: str
    import_request_id: str
    source_id: str
    origin_reference_id: str
    repository_identity: str
    workflow_identity: str
    run_id: str
    run_attempt: int
    head_sha: str
    artifact_id: str
    artifact_name: str
    provider_digest: str
    downloaded_checksum: str
    evidence_package_id: str
    evidence_package_checksum: str
    technical_verification_status: str
    trust_status: str
    imported_at: str
    attestation_signer_reference_id: str
    signature_envelope: CertificationSignatureEnvelope


@dataclass(frozen=True)
class CiArtifactRetentionPolicy:
    workspace_id: str
    retain_downloaded_archive: bool
    archive_maximum_age_seconds: int
    retain_normalized_package: bool
    normalized_package_maximum_age_seconds: int
    retain_import_attestation: bool
    retain_audit_history: bool
    minimum_verified_packages: int
    legal_hold_behavior: str
    maximum_total_bytes: int
    version: int


@dataclass(frozen=True)
class CiImportAuditEvent:
    id: str
    action: str
    import_request_id: str
    actor: str
    safe_summary: str
    occurred_at: str


def default_retention_policy(workspace_id: str = "workspace-1") -> CiArtifactRetentionPolicy:
    return CiArtifactRetentionPolicy(
        workspace_id=workspace_id,
        retain_downloaded_archive=False,
        archive_maximum_age_seconds=86400,
        retain_normalized_package=True,
        normalized_package_maximum_age_seconds=2_592_000,
        retain_import_attestation=True,
        retain_audit_history=True,
        minimum_verified_packages=1,
        legal_hold_behavior="preserve",
        maximum_total_bytes=50_000_000,
        version=1,
    )


def import_request_id(origin_id: str, run_id: str, run_attempt: int, artifact_id: str) -> str:
    return f"ci-import-{origin_id}-{run_id}-{run_attempt}-{artifact_id}".replace("/", "-")


__all__ = [
    "CiArtifactImportAttestation",
    "CiArtifactImportRequest",
    "CiArtifactRetentionPolicy",
    "CiImportAuditEvent",
    "CiWorkflowArtifact",
    "CiWorkflowRun",
    "default_retention_policy",
    "import_request_id",
    "utc_now_iso",
]
