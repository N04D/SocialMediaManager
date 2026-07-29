"""Operator roles and approval checks."""

from __future__ import annotations

from src.core.certification_evidence.models import stable_checksum, utc_now_iso

from .errors import ManagedSecretError
from .models import ManagedSecretApproval, OperatorRoleBinding, approval_policy
from .persistence import ManagedSecretRepository


class OperatorAuthorizationService:
    def __init__(self, repository: ManagedSecretRepository) -> None:
        self.repository = repository

    def grant_role(self, operator_id: str, role: str, *, scope: str = "host") -> dict:
        return self.repository.bind_role(
            OperatorRoleBinding(
                operator_id=operator_id,
                role=role,
                workspace_id_or_host_scope=scope,
                granted_at=utc_now_iso(),
            )
        )

    def require_role(self, operator_id: str, allowed_roles: tuple[str, ...]) -> None:
        roles = self.repository.roles(operator_id)
        if not set(roles).intersection(allowed_roles):
            raise ManagedSecretError("operator.role_required", "Operator role does not permit this action.")

    def approve(
        self,
        *,
        reference: dict,
        action_type: str,
        requester_id: str,
        approver_id: str,
    ) -> dict:
        policy = approval_policy(action_type)
        if policy.approval_required:
            self.require_role(approver_id, policy.allowed_roles)
        if not policy.self_approval_allowed and requester_id == approver_id:
            raise ManagedSecretError("operator.self_approval_blocked", "Independent approval is required.")
        approval = ManagedSecretApproval(
            id="secret-approval-"
            + stable_checksum(
                {
                    "reference": reference["id"],
                    "action": action_type,
                    "version": reference["version"],
                    "approver": approver_id,
                }
            )[:20],
            secret_reference_id=reference["id"],
            action_type=action_type,
            resource_version=int(reference["version"]),
            resource_fingerprint=str(reference.get("safe_fingerprint", "")),
            requester_id=requester_id,
            approver_id=approver_id,
            decision="approved",
            approved_at=utc_now_iso(),
            expires_at="",
        )
        return self.repository.save_approval(approval)

    def approval_satisfied(self, reference: dict, action_type: str) -> bool:
        policy = approval_policy(action_type)
        if not policy.approval_required:
            return True
        approvals = self.repository.approvals(reference["id"], action_type)
        valid = [
            item
            for item in approvals
            if item.get("decision") == "approved"
            and int(item.get("resource_version", -1)) == int(reference["version"])
            and item.get("resource_fingerprint") == reference.get("safe_fingerprint", "")
        ]
        return len(valid) >= policy.minimum_approvals


__all__ = ["OperatorAuthorizationService"]
