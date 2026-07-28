"""Certification trust policy evaluation."""

from __future__ import annotations

from .models import (
    CertificationCiOriginReference,
    CertificationEvidencePackage,
    CertificationProvenance,
    CertificationTrustPolicy,
    utc_now_iso,
)


def default_trust_policy(workspace_id: str = "workspace-1") -> CertificationTrustPolicy:
    now = utc_now_iso()
    return CertificationTrustPolicy(
        id="cert-trust-default",
        workspace_id=workspace_id,
        trusted_signer_reference_ids=("signer.local.deterministic-test",),
        trusted_ci_origins=("ci.github.owned-publication",),
        accepted_evidence_types=(
            "browser_certification",
            "worker_certification",
            "instrumentation_certification",
            "deterministic_staging_certification",
            "staging_provider_certification",
            "owned_publication_release_readiness",
        ),
        accepted_source_types=("local", "ci", "staging", "imported"),
        require_exact_commit=True,
        require_signature_for_ci=True,
        require_signature_for_staging=False,
        minimum_trust_level="unsigned_local",
        version=1,
        created_at=now,
        updated_at=now,
    )


def default_ci_origin() -> CertificationCiOriginReference:
    return CertificationCiOriginReference(
        id="ci.github.owned-publication",
        provider="github_actions",
        repository_identity="SocialMediaManager",
        workflow_identity="Owned Publication Certification Evidence",
        environment_identity="deterministic",
        artifact_name_pattern="certification-evidence-*.zip",
        enabled=True,
    )


def evaluate_trust(
    *,
    package: CertificationEvidencePackage,
    provenance: CertificationProvenance,
    signature_status: str,
    policy: CertificationTrustPolicy,
    current_commit: str,
    revoked: bool = False,
    ci_origin: CertificationCiOriginReference | None = None,
) -> str:
    if revoked:
        return "revoked"
    if (
        package.evidence_type not in policy.accepted_evidence_types
        or provenance.source_type not in policy.accepted_source_types
    ):
        return "untrusted"
    if policy.require_exact_commit and provenance.commit_sha != current_commit:
        return "untrusted"
    if provenance.required_skips > 0:
        return "invalid"
    if (
        package.evidence_type == "staging_provider_certification"
        and provenance.staging_execution_status == "provider_observed"
    ):
        return "verified_staging_provider"
    if provenance.source_type == "ci":
        if ci_origin is None or not ci_origin.enabled:
            return "untrusted"
        if policy.require_signature_for_ci and signature_status != "valid":
            return "untrusted"
        return "verified_ci_artifact"
    if (
        signature_status == "valid"
        and package.signature_envelope.signer_reference_id in policy.trusted_signer_reference_ids
    ):
        return "signed_local"
    if signature_status == "not_configured" and provenance.source_type == "local":
        return "unsigned_local"
    if signature_status in {"invalid", "payload_mismatch"}:
        return "invalid"
    return "untrusted"


__all__ = ["default_ci_origin", "default_trust_policy", "evaluate_trust"]
