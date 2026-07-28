"""Integrity checks and safe repairs for certification evidence."""

from __future__ import annotations


def integrity_findings(packages: list[dict]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for package in packages:
        if not package.get("artifact_manifest"):
            findings.append(
                {"code": "certification.package.missing_manifest", "package_id": package.get("package_id", "")}
            )
        if package.get("trust_status") == "verified_ci_artifact" and package.get("signature_status") != "valid":
            findings.append({"code": "certification.ci.unsigned_trusted", "package_id": package.get("package_id", "")})
        report = package.get("report", {})
        if report.get("live_staging_executed") and report.get("provider_observed_status") != "observed":
            findings.append(
                {"code": "certification.false_live_staging_claim", "package_id": package.get("package_id", "")}
            )
    return findings


def safe_repairs() -> tuple[str, ...]:
    return (
        "recalculate_trust_status",
        "recalculate_freshness_status",
        "reverify_package",
        "rebuild_comparison",
        "rebuild_readiness_index",
    )


__all__ = ["integrity_findings", "safe_repairs"]
