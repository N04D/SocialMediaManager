"""Models for host-owned certification signers."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.certification_evidence.models import utc_now_iso

SIGNER_STATUSES = (
    "pending_validation",
    "pending_approval",
    "active",
    "degraded",
    "disabled",
    "rotated",
    "revoked",
    "invalid",
)


@dataclass(frozen=True)
class TrustedSignerReference:
    id: str
    workspace_id_or_host_scope: str
    display_name: str
    signer_type: str
    algorithm_identifier: str
    private_key_secret_reference: str
    public_key: str
    public_key_fingerprint: str
    allowed_evidence_types: tuple[str, ...]
    allowed_source_types: tuple[str, ...]
    status: str
    approved_by: str
    approved_at: str
    activated_at: str
    rotated_from_signer_id: str
    revoked_at: str
    revocation_reason: str
    created_at: str
    updated_at: str
    version: int


@dataclass(frozen=True)
class SignerApproval:
    id: str
    signer_id: str
    reviewer_id: str
    decision: str
    approved_at: str
    version: int = 1


@dataclass(frozen=True)
class SignerApprovalPolicy:
    approval_required: bool = True
    minimum_approvals: int = 1
    allowed_roles: tuple[str, ...] = ("operator", "security")
    self_approval_allowed: bool = False


@dataclass(frozen=True)
class SignerHealthReport:
    signer_id: str
    status: str
    secret_reference_exists: bool
    secret_readable: bool
    key_format_valid: bool
    key_pair_valid: bool
    algorithm_allowed: bool
    fingerprint_matches: bool
    approval_valid: bool
    sign_verify_probe: bool
    safe_error_code: str
    checked_at: str


@dataclass(frozen=True)
class SignerRotationRecord:
    id: str
    old_signer_id: str
    new_signer_id: str
    reason: str
    rotated_at: str
    actor: str


@dataclass(frozen=True)
class SignerAuditEvent:
    id: str
    action: str
    signer_id: str
    actor: str
    safe_summary: str
    occurred_at: str


def signer_record(
    *,
    signer_id: str,
    display_name: str,
    secret_reference: str,
    public_key: str,
    fingerprint: str,
    status: str = "pending_approval",
    approved_by: str = "",
    activated_at: str = "",
    rotated_from: str = "",
) -> TrustedSignerReference:
    now = utc_now_iso()
    return TrustedSignerReference(
        id=signer_id,
        workspace_id_or_host_scope="host",
        display_name=display_name,
        signer_type="host_owned",
        algorithm_identifier="Ed25519",
        private_key_secret_reference=secret_reference,
        public_key=public_key,
        public_key_fingerprint=fingerprint,
        allowed_evidence_types=(
            "browser_certification",
            "worker_certification",
            "instrumentation_certification",
            "deterministic_staging_certification",
            "staging_provider_certification",
            "owned_publication_release_readiness",
        ),
        allowed_source_types=("local", "ci", "staging", "imported"),
        status=status,
        approved_by=approved_by,
        approved_at=now if approved_by else "",
        activated_at=activated_at,
        rotated_from_signer_id=rotated_from,
        revoked_at="",
        revocation_reason="",
        created_at=now,
        updated_at=now,
        version=1,
    )


__all__ = [
    "SIGNER_STATUSES",
    "SignerApproval",
    "SignerApprovalPolicy",
    "SignerAuditEvent",
    "SignerHealthReport",
    "SignerRotationRecord",
    "TrustedSignerReference",
    "signer_record",
]
