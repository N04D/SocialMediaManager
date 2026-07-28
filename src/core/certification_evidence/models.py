"""Certification evidence trust models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


TRUST_LEVELS = (
    "unsigned_local",
    "signed_local",
    "verified_ci_artifact",
    "verified_staging_provider",
    "invalid",
    "untrusted",
    "stale",
    "revoked",
)

EVIDENCE_TYPES = (
    "browser_certification",
    "worker_certification",
    "instrumentation_certification",
    "deterministic_staging_certification",
    "staging_provider_certification",
    "owned_publication_release_readiness",
)


@dataclass(frozen=True)
class CertificationArtifactManifest:
    artifact_path: str
    artifact_type: str
    media_type: str
    size_bytes: int
    checksum_algorithm: str
    checksum: str
    required: bool
    redaction_status: str


@dataclass(frozen=True)
class CertificationProvenance:
    provenance_version: str
    source_type: str
    repository_identity: str
    commit_sha: str
    branch: str
    dirty_state: str
    test_suite_id: str
    test_suite_version: str
    test_commands: tuple[str, ...]
    test_result_checksum: str
    required_tests: tuple[str, ...]
    required_skips: int
    browser_name: str
    browser_version: str
    worker_execution_model: str
    database_type: str
    instrumentation_version: str
    analytics_provider_id: str
    staging_execution_status: str
    generated_by: str
    generated_at: str


@dataclass(frozen=True)
class CertificationSignatureEnvelope:
    signature_version: str
    signer_reference_id: str
    algorithm_identifier: str
    signed_payload_checksum: str
    signature: str
    public_key_fingerprint: str
    signed_at: str
    signature_status: str


@dataclass(frozen=True)
class CertificationEvidencePackage:
    package_id: str
    package_version: str
    evidence_type: str
    workspace_id: str
    source_environment: str
    source_origin: str
    generated_at: str
    report_reference: str
    provenance_reference: str
    artifact_manifest: tuple[CertificationArtifactManifest, ...]
    signature_envelope: CertificationSignatureEnvelope
    package_checksum: str


@dataclass(frozen=True)
class CertificationSignerReference:
    id: str
    display_name: str
    signer_type: str
    public_key_reference: str
    private_key_secret_reference: str
    allowed_evidence_types: tuple[str, ...]
    allowed_source_types: tuple[str, ...]
    trust_scope: str
    enabled: bool
    revoked_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CertificationSigningPolicy:
    evidence_type: str
    signing_required: bool
    allowed_signers: tuple[str, ...]
    allowed_source_types: tuple[str, ...]
    maximum_signature_age: str
    unsigned_behavior: str


@dataclass(frozen=True)
class CertificationTrustPolicy:
    id: str
    workspace_id: str
    trusted_signer_reference_ids: tuple[str, ...]
    trusted_ci_origins: tuple[str, ...]
    accepted_evidence_types: tuple[str, ...]
    accepted_source_types: tuple[str, ...]
    require_exact_commit: bool
    require_signature_for_ci: bool
    require_signature_for_staging: bool
    minimum_trust_level: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CertificationCiOriginReference:
    id: str
    provider: str
    repository_identity: str
    workflow_identity: str
    environment_identity: str
    artifact_name_pattern: str
    enabled: bool
    revoked_at: str = ""


@dataclass(frozen=True)
class CertificationFreshnessPolicy:
    id: str
    workspace_id: str
    evidence_type: str
    maximum_age_seconds: int
    warning_age_seconds: int
    require_same_commit: bool
    require_same_framework_version: bool
    require_same_browser_major: bool
    require_same_provider_adapter_version: bool
    stale_behavior: str
    version: int


@dataclass(frozen=True)
class CertificationImportRecord:
    package_id: str
    package_checksum: str
    signer_reference_id: str
    imported_at: str
    import_source: str
    trust_status: str
    first_seen_at: str


@dataclass(frozen=True)
class CertificationEvidenceReview:
    id: str
    workspace_id: str
    evidence_id: str
    reviewer_id: str
    decision: str
    safe_comment: str
    reviewed_at: str
    evidence_checksum: str


@dataclass(frozen=True)
class CertificationRevocation:
    id: str
    workspace_id: str
    target_type: str
    target_id: str
    reason: str
    revoked_at: str
    revoked_by: str


@dataclass(frozen=True)
class CertificationEvidenceComparison:
    left_evidence_id: str
    right_evidence_id: str
    shared_commit: bool
    shared_profile: bool
    deterministic_status: str
    staging_status: str
    browser_differences: tuple[str, ...]
    instrumentation_differences: tuple[str, ...]
    mapping_differences: tuple[str, ...]
    provider_observation_differences: tuple[str, ...]
    freshness_differences: tuple[str, ...]
    trust_differences: tuple[str, ...]
    regression_findings: tuple[str, ...]
    compared_at: str


def package_with_checksum(package: CertificationEvidencePackage) -> CertificationEvidencePackage:
    payload = asdict(package)
    payload["package_checksum"] = ""
    return replace(package, package_checksum=stable_checksum(payload))


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def age_status(completed_at: str, *, now: str, policy: CertificationFreshnessPolicy) -> str:
    age = parse_utc(now) - parse_utc(completed_at)
    if age > timedelta(seconds=policy.maximum_age_seconds):
        return "stale"
    if age > timedelta(seconds=policy.warning_age_seconds):
        return "warning"
    return "fresh"


__all__ = [name for name in globals() if name.startswith("Certification") or name in {"EVIDENCE_TYPES", "TRUST_LEVELS"}]
