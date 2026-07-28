"""Evidence comparison helpers."""

from __future__ import annotations

from .models import CertificationEvidenceComparison, utc_now_iso


def compare_evidence(left: dict, right: dict) -> CertificationEvidenceComparison:
    left_provenance = left.get("provenance", {})
    right_provenance = right.get("provenance", {})
    shared_commit = left_provenance.get("commit_sha") == right_provenance.get("commit_sha")
    shared_profile = left.get("report", {}).get("profile_id") == right.get("report", {}).get("profile_id")
    limitations: list[str] = []
    if not shared_commit:
        limitations.append("commit_mismatch_limited_comparison")
    if not shared_profile:
        limitations.append("profile_mismatch_limited_comparison")
    mapping_differences = ()
    if left.get("report", {}).get("mapping_status") != right.get("report", {}).get("mapping_status"):
        mapping_differences = ("mapping_status_differs",)
    return CertificationEvidenceComparison(
        left_evidence_id=left["package_id"],
        right_evidence_id=right["package_id"],
        shared_commit=shared_commit,
        shared_profile=shared_profile,
        deterministic_status=left.get("report", {}).get("provider_observed_status", "unknown"),
        staging_status=right.get("report", {}).get("provider_observed_status", "unknown"),
        browser_differences=(),
        instrumentation_differences=(),
        mapping_differences=mapping_differences,
        provider_observation_differences=tuple(limitations),
        freshness_differences=()
        if left.get("freshness_status") == right.get("freshness_status")
        else ("freshness_differs",),
        trust_differences=() if left.get("trust_status") == right.get("trust_status") else ("trust_differs",),
        regression_findings=tuple(limitations),
        compared_at=utc_now_iso(),
    )


__all__ = ["compare_evidence"]
