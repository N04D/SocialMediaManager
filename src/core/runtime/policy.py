from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .capabilities import CapabilityDescriptor, CapabilityMode
from .components import ComponentManifest
from .deployments import PlaybookDeployment
from .events import utc_now_iso
from .execution_context import ExecutionContext
from .installs import Install
from .permissions import (
    EffectivePermissionSet,
    PermissionContext,
    capability_permission_requirements,
    validate_component_permissions,
)
from .plans import ExecutionPlanNode
from .resolver import RuntimeRegistry


class PolicyReasonCode(StrEnum):
    ALLOW = "ALLOW"
    CAPABILITY_NOT_GRANTED = "CAPABILITY_NOT_GRANTED"
    CAPABILITY_EXPLICITLY_DENIED = "CAPABILITY_EXPLICITLY_DENIED"
    MUTATION_NOT_ALLOWED = "MUTATION_NOT_ALLOWED"
    NETWORK_NOT_ALLOWED = "NETWORK_NOT_ALLOWED"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    SECRET_NOT_GRANTED = "SECRET_NOT_GRANTED"
    SECRET_REF_MISSING = "SECRET_REF_MISSING"
    FILESYSTEM_ACCESS_NOT_ALLOWED = "FILESYSTEM_ACCESS_NOT_ALLOWED"
    SUBPROCESS_NOT_ALLOWED = "SUBPROCESS_NOT_ALLOWED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INSTALL_DISABLED = "INSTALL_DISABLED"
    DEPLOYMENT_DISABLED = "DEPLOYMENT_DISABLED"
    COMPONENT_CAPABILITY_MISSING = "COMPONENT_CAPABILITY_MISSING"


@dataclass(frozen=True)
class EffectivePermission:
    capability_id: str
    capability_mode: str
    component_id: str
    install_id: str
    network_required: bool = False
    network_allowed: bool = False
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    secret_refs_required: tuple[str, ...] = field(default_factory=tuple)
    secret_refs_granted: tuple[str, ...] = field(default_factory=tuple)
    filesystem_required: str = "none"
    filesystem_allowed: bool = False
    subprocess_required: bool = False
    subprocess_allowed: bool = False
    permission_set: EffectivePermissionSet | None = None
    mutation: bool = False
    mutation_allowed: bool = False
    approval_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_domains": list(self.allowed_domains),
            "approval_required": self.approval_required,
            "capability_id": self.capability_id,
            "capability_mode": self.capability_mode,
            "component_id": self.component_id,
            "filesystem_allowed": self.filesystem_allowed,
            "filesystem_required": self.filesystem_required,
            "install_id": self.install_id,
            "mutation": self.mutation,
            "mutation_allowed": self.mutation_allowed,
            "network_allowed": self.network_allowed,
            "network_required": self.network_required,
            "secret_refs_granted": list(self.secret_refs_granted),
            "secret_refs_required": list(self.secret_refs_required),
            "subprocess_allowed": self.subprocess_allowed,
            "subprocess_required": self.subprocess_required,
            "permissions": self.permission_set.to_dict() if self.permission_set else {},
        }

    def permission_context(self, roots: dict[str, str] | None = None) -> PermissionContext:
        if self.permission_set is None:
            raise RuntimeError("Effective permission set is not available.")
        return PermissionContext(self.permission_set, dict(roots or {}))


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason_code: str
    required_approval: bool = False
    effective_permission: EffectivePermission | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "effective_permission": self.effective_permission.to_dict() if self.effective_permission else {},
            "metadata": dict(self.metadata),
            "reason_code": self.reason_code,
            "required_approval": self.required_approval,
        }


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalRecord:
    execution_id: str
    node_id: str
    capability_id: str
    status: str = ApprovalStatus.PENDING.value
    requested_at: str = field(default_factory=utc_now_iso)
    decided_at: str = ""
    actor: str = ""
    actor_id: str = ""
    actor_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    approval_id: str = field(default_factory=lambda: f"approval_{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "approval_id": self.approval_id,
            "capability_id": self.capability_id,
            "decided_at": self.decided_at,
            "execution_id": self.execution_id,
            "metadata": dict(self.metadata),
            "node_id": self.node_id,
            "requested_at": self.requested_at,
            "status": self.status,
        }


@dataclass
class InMemoryApprovalStore:
    approvals: dict[tuple[str, str], ApprovalRecord] = field(default_factory=dict)

    def get(self, execution_id: str, node_id: str) -> ApprovalRecord | None:
        return self.approvals.get((execution_id, node_id))

    def request(
        self,
        *,
        execution_id: str,
        node_id: str,
        capability_id: str,
        metadata: dict[str, Any] | None = None,
        replace_existing: bool = False,
    ) -> ApprovalRecord:
        key = (execution_id, node_id)
        existing = self.approvals.get(key)
        if existing is not None and not replace_existing:
            return existing
        record = ApprovalRecord(
            execution_id=execution_id,
            node_id=node_id,
            capability_id=capability_id,
            metadata=dict(metadata or {}),
        )
        self.approvals[key] = record
        return record

    def approve(
        self,
        execution_id: str,
        node_id: str,
        *,
        actor: str = "",
        actor_id: str = "",
        actor_type: str = "",
    ) -> ApprovalRecord:
        record = self.approvals[(execution_id, node_id)]
        if record.status == ApprovalStatus.APPROVED.value:
            return record
        approved = replace(
            record,
            status=ApprovalStatus.APPROVED.value,
            decided_at=utc_now_iso(),
            actor=actor,
            actor_id=actor_id,
            actor_type=actor_type,
        )
        self.approvals[(execution_id, node_id)] = approved
        return approved

    def reject(
        self,
        execution_id: str,
        node_id: str,
        *,
        actor: str = "",
        actor_id: str = "",
        actor_type: str = "",
    ) -> ApprovalRecord:
        record = self.approvals[(execution_id, node_id)]
        rejected = replace(
            record,
            status=ApprovalStatus.REJECTED.value,
            decided_at=utc_now_iso(),
            actor=actor,
            actor_id=actor_id,
            actor_type=actor_type,
        )
        self.approvals[(execution_id, node_id)] = rejected
        return rejected


class RuntimePolicyEngine:
    def __init__(self, *, registry: RuntimeRegistry, deployments: dict[str, PlaybookDeployment]):
        self.registry = registry
        self.deployments = dict(deployments)

    def evaluate(
        self,
        *,
        execution_context: ExecutionContext,
        plan_node: ExecutionPlanNode,
        approval: ApprovalRecord | None = None,
    ) -> PolicyDecision:
        deployment = self.deployments.get(execution_context.deployment_id)
        install = self.registry.installs.get(plan_node.install_id)
        component = self.registry.components.get(plan_node.component_id)
        if deployment is None or not deployment.enabled:
            return _deny(PolicyReasonCode.DEPLOYMENT_DISABLED)
        if install is None or not install.enabled:
            return _deny(PolicyReasonCode.INSTALL_DISABLED)
        if component is None:
            return _deny(PolicyReasonCode.COMPONENT_CAPABILITY_MISSING)
        capability = component.capability(plan_node.capability)
        if capability is None:
            return _deny(PolicyReasonCode.COMPONENT_CAPABILITY_MISSING)

        effective = _effective_permission(capability, component, install, deployment)
        if install.grants.denies_capability(capability.capability_id):
            return _deny(PolicyReasonCode.CAPABILITY_EXPLICITLY_DENIED, effective)
        if not install.grants.allows_capability(capability.capability_id):
            return _deny(PolicyReasonCode.CAPABILITY_NOT_GRANTED, effective)
        if effective.mutation and not effective.mutation_allowed:
            return _deny(PolicyReasonCode.MUTATION_NOT_ALLOWED, effective)
        if effective.network_required and not effective.network_allowed:
            return _deny(PolicyReasonCode.NETWORK_NOT_ALLOWED, effective)
        if effective.network_required and not _domains_allowed(effective.allowed_domains, install, deployment):
            return _deny(PolicyReasonCode.DOMAIN_NOT_ALLOWED, effective)
        if effective.filesystem_required != "none" and not effective.filesystem_allowed:
            return _deny(PolicyReasonCode.FILESYSTEM_ACCESS_NOT_ALLOWED, effective)
        if effective.subprocess_required and not effective.subprocess_allowed:
            return _deny(PolicyReasonCode.SUBPROCESS_NOT_ALLOWED, effective)
        for secret_ref in effective.secret_refs_required:
            if secret_ref not in install.secret_refs:
                return _deny(PolicyReasonCode.SECRET_REF_MISSING, effective)
            if secret_ref not in install.grants.allowed_secret_refs:
                return _deny(PolicyReasonCode.SECRET_NOT_GRANTED, effective)
        permission_validation = validate_component_permissions(
            requested=capability_permission_requirements(component, capability.capability_id),
            grants=_permission_grants_for_install(install),
        )
        if not permission_validation.ready:
            reason = {
                "MISSING_FILESYSTEM_PERMISSION": PolicyReasonCode.FILESYSTEM_ACCESS_NOT_ALLOWED,
                "MISSING_OPERATION_PERMISSION": PolicyReasonCode.SUBPROCESS_NOT_ALLOWED,
                "MISSING_EGRESS_PERMISSION": PolicyReasonCode.DOMAIN_NOT_ALLOWED,
            }.get(permission_validation.reason_code, PolicyReasonCode.COMPONENT_CAPABILITY_MISSING)
            return _deny(reason, effective, _decision_metadata(effective, reason.value))
        if effective.approval_required and (approval is None or approval.status != ApprovalStatus.APPROVED.value):
            return PolicyDecision(
                allowed=True,
                reason_code=PolicyReasonCode.APPROVAL_REQUIRED.value,
                required_approval=True,
                effective_permission=effective,
                metadata=_decision_metadata(effective, PolicyReasonCode.APPROVAL_REQUIRED.value),
            )
        return PolicyDecision(
            allowed=True,
            reason_code=PolicyReasonCode.ALLOW.value,
            effective_permission=effective,
            metadata=_decision_metadata(effective, PolicyReasonCode.ALLOW.value),
        )


def _deny(
    reason: PolicyReasonCode, effective: EffectivePermission | None = None, metadata: dict[str, Any] | None = None
) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason_code=reason.value,
        effective_permission=effective,
        metadata=metadata or (_decision_metadata(effective, reason.value) if effective else {}),
    )


def _effective_permission(
    capability: CapabilityDescriptor,
    component: ComponentManifest,
    install: Install,
    deployment: PlaybookDeployment,
) -> EffectivePermission:
    permissions = dict(component.permissions or {})
    network = dict(permissions.get("network") or component.network_policy or {})
    filesystem = dict(permissions.get("filesystem") or {})
    subprocess = dict(permissions.get("subprocess") or {})
    secret_refs = tuple(str(item) for item in capability.policy.get("required_secret_refs", ()))
    requested_permissions = capability_permission_requirements(component, capability.capability_id)
    permission_validation = validate_component_permissions(
        requested=requested_permissions,
        grants=_permission_grants_for_install(install),
    )
    permission_set = permission_validation.effective
    mutation = capability.mode == CapabilityMode.WRITE.value
    approval_required = capability.capability_id in deployment.policy.approval_required_capabilities or (
        mutation and (deployment.policy.require_approval_for_writes or install.grants.require_approval_for_writes)
    )
    domains = tuple(str(item) for item in network.get("allowed_domains", ()))
    return EffectivePermission(
        capability_id=capability.capability_id,
        capability_mode=capability.mode,
        component_id=component.component_id,
        install_id=install.install_id,
        network_required=bool(network.get("required", False)),
        network_allowed=bool(install.grants.allow_network and deployment.policy.allow_network),
        allowed_domains=domains,
        secret_refs_required=secret_refs,
        secret_refs_granted=tuple(item for item in secret_refs if item in install.grants.allowed_secret_refs),
        filesystem_required=str(filesystem.get("mode") or "none"),
        filesystem_allowed=bool(install.grants.allow_filesystem and deployment.policy.allow_filesystem),
        subprocess_required=bool(subprocess.get("allowed", False)),
        subprocess_allowed=bool(install.grants.allow_subprocess and deployment.policy.allow_subprocess),
        permission_set=permission_set,
        mutation=mutation,
        mutation_allowed=bool(install.grants.allow_mutations and deployment.policy.allow_mutations),
        approval_required=approval_required,
    )


def _domains_allowed(domains: tuple[str, ...], install: Install, deployment: PlaybookDeployment) -> bool:
    install_domains = set(install.grants.allowed_network_domains)
    deployment_domains = set(deployment.policy.allowed_network_domains)
    if not domains:
        return True
    if not install_domains or not deployment_domains:
        return False
    return set(domains).issubset(install_domains) and set(domains).issubset(deployment_domains)


def _permission_grants_for_install(install: Install) -> Any:
    from .permissions import InstallPermissionGrants

    grants = install.grants.permission_grants
    if not install.grants.allowed_network_domains or grants.network.egress:
        return grants
    payload = grants.to_dict()
    payload["network"] = {"egress": [{"host": host, "port": 443} for host in install.grants.allowed_network_domains]}
    return InstallPermissionGrants.from_dict(payload)


def _decision_metadata(effective: EffectivePermission | None, reason_code: str) -> dict[str, Any]:
    if effective is None:
        return {"policy_decision": "deny", "reason_code": reason_code}
    return {
        "approval_required": effective.approval_required,
        "capability": effective.capability_id,
        "component_id": effective.component_id,
        "filesystem_required": effective.filesystem_required,
        "install_id": effective.install_id,
        "mutation": effective.mutation,
        "network_required": effective.network_required,
        "policy_decision": "allow" if reason_code == PolicyReasonCode.ALLOW.value else "deny",
        "reason_code": reason_code,
        "access_scope": "granted"
        if set(effective.secret_refs_required).issubset(set(effective.secret_refs_granted))
        else "not_granted",
        "subprocess_required": effective.subprocess_required,
        "effective_permissions": effective.permission_set.to_dict()["effective"] if effective.permission_set else {},
    }
