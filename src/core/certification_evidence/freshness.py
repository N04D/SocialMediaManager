"""Certification freshness policy."""

from __future__ import annotations

from .models import CertificationFreshnessPolicy, CertificationProvenance, age_status


def default_freshness_policy(
    workspace_id: str = "workspace-1", evidence_type: str = "deterministic_staging_certification"
) -> CertificationFreshnessPolicy:
    return CertificationFreshnessPolicy(
        id=f"freshness-{evidence_type}",
        workspace_id=workspace_id,
        evidence_type=evidence_type,
        maximum_age_seconds=7 * 24 * 3600,
        warning_age_seconds=24 * 3600,
        require_same_commit=True,
        require_same_framework_version=True,
        require_same_browser_major=True,
        require_same_provider_adapter_version=True,
        stale_behavior="degrade",
        version=1,
    )


def freshness_status(
    *,
    provenance: CertificationProvenance,
    policy: CertificationFreshnessPolicy,
    current_commit: str,
    current_framework_version: str,
    now: str,
) -> str:
    if policy.require_same_commit and provenance.commit_sha != current_commit:
        return "stale"
    if (
        policy.require_same_framework_version
        and provenance.test_suite_version.split(".")[0] != current_framework_version.split(".")[0]
    ):
        return "stale"
    return age_status(provenance.generated_at, now=now, policy=policy)


__all__ = ["default_freshness_policy", "freshness_status"]
