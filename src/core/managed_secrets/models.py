"""Models for managed secret metadata and safe operational state."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.certification_evidence.models import stable_checksum, utc_now_iso

SECRET_TYPES = (
    "ed25519_private_key",
    "github_read_only_token",
    "analytics_api_token",
    "generic_api_token",
    "master_key",
)

SECRET_PURPOSES = (
    "certification_signing",
    "github_actions_read",
    "plausible_stats_read",
)

SECRET_REFERENCE_STATUSES = (
    "pending_value",
    "pending_validation",
    "pending_approval",
    "active",
    "degraded",
    "expired",
    "disabled",
    "rotated",
    "revoked",
    "invalid",
)

OPERATOR_ROLES = (
    "secret_operator",
    "security_approver",
    "release_operator",
    "auditor",
    "workspace_admin",
)


@dataclass(frozen=True)
class ManagedSecretReference:
    id: str
    workspace_id_or_host_scope: str
    backend_id: str
    secret_type: str
    display_name: str
    purpose_allowlist: tuple[str, ...]
    current_version: int
    status: str
    created_by: str
    approved_by: str
    created_at: str
    updated_at: str
    rotated_at: str
    expires_at: str
    revoked_at: str
    safe_fingerprint: str
    version: int


@dataclass(frozen=True)
class ManagedSecretVersion:
    id: str
    secret_reference_id: str
    secret_version: int
    backend_id: str
    backend_record_reference: str
    status: str
    safe_fingerprint: str
    created_at: str
    activated_at: str
    revoked_at: str


@dataclass(frozen=True)
class SecretLease:
    lease_id: str
    secret_reference_id: str
    secret_version: int
    purpose: str
    consumer: str
    acquired_at: str
    expires_at: str


@dataclass(frozen=True)
class ManagedSecretApproval:
    id: str
    secret_reference_id: str
    action_type: str
    resource_version: int
    resource_fingerprint: str
    requester_id: str
    approver_id: str
    decision: str
    approved_at: str
    expires_at: str


@dataclass(frozen=True)
class OperatorRoleBinding:
    operator_id: str
    role: str
    workspace_id_or_host_scope: str
    granted_at: str


@dataclass(frozen=True)
class OperatorApprovalPolicy:
    action_type: str
    approval_required: bool
    minimum_approvals: int
    allowed_roles: tuple[str, ...]
    self_approval_allowed: bool
    approval_expiry_seconds: int


@dataclass(frozen=True)
class ManagedSecretHealthReport:
    secret_reference_id: str
    status: str
    backend_record_exists: bool
    active_value_present: bool
    purpose_allowlist_valid: bool
    approval_satisfied: bool
    expired: bool
    revoked: bool
    safe_error_code: str
    checked_at: str


@dataclass(frozen=True)
class ManagedSecretVaultHealthReport:
    backend_id: str
    backend_version: str
    vault_location_reference: str
    master_key_source: str
    master_key_fingerprint: str
    permissions_status: str
    storage_status: str
    encryption_probe: str
    decryption_probe: str
    atomic_write_status: str
    corruption_status: str
    secret_count: int
    active_secret_count: int
    degraded_secret_count: int
    expired_secret_count: int
    ready: bool
    safe_warnings: tuple[str, ...]


@dataclass(frozen=True)
class ManagedSecretAuditEvent:
    id: str
    action: str
    resource_id: str
    resource_version: int
    purpose: str
    actor: str
    result: str
    safe_error_code: str
    occurred_at: str


def secret_reference_id(secret_type: str, display_name: str) -> str:
    return "secretref:" + stable_checksum({"type": secret_type, "name": display_name, "at": utc_now_iso()})[:24]


def approval_policy(action_type: str) -> OperatorApprovalPolicy:
    if action_type in {
        "activate_production_signer",
        "approve_github_credential",
        "rotate_active_signer",
        "revoke_signer",
        "change_secret_backend",
    }:
        return OperatorApprovalPolicy(
            action_type=action_type,
            approval_required=True,
            minimum_approvals=1,
            allowed_roles=("security_approver",),
            self_approval_allowed=False,
            approval_expiry_seconds=24 * 3600,
        )
    return OperatorApprovalPolicy(
        action_type=action_type,
        approval_required=False,
        minimum_approvals=0,
        allowed_roles=("secret_operator", "security_approver"),
        self_approval_allowed=False,
        approval_expiry_seconds=24 * 3600,
    )


__all__ = [
    "ManagedSecretApproval",
    "ManagedSecretAuditEvent",
    "ManagedSecretHealthReport",
    "ManagedSecretReference",
    "ManagedSecretVaultHealthReport",
    "ManagedSecretVersion",
    "OPERATOR_ROLES",
    "OperatorApprovalPolicy",
    "OperatorRoleBinding",
    "SECRET_PURPOSES",
    "SECRET_REFERENCE_STATUSES",
    "SECRET_TYPES",
    "SecretLease",
    "approval_policy",
    "secret_reference_id",
]
