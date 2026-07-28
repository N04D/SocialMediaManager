"""Synthetic certification evidence fixtures."""

from __future__ import annotations


def canonical_report_fixture() -> dict:
    return {
        "framework_version": "0.1.0",
        "profile_id": "staging-cert-profile-1",
        "run_id": "smm_synthetic_run_fixture",
        "provider_observed_status": "observed",
        "mapping_status": "aligned",
        "attribution_status": "exact_attribution_id",
        "certification_passed": True,
        "live_staging_executed": False,
        "deterministic_only": True,
        "safe_warnings": ("staging_provider_certification_not_run",),
    }


def ci_origin_payload() -> dict:
    return {
        "id": "ci.github.owned-publication",
        "provider": "github_actions",
        "repository_identity": "SocialMediaManager",
        "workflow_identity": "Owned Publication Certification Evidence",
        "environment_identity": "deterministic",
        "artifact_name_pattern": "certification-evidence-*.zip",
    }
