from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import CapabilityResolutionError, DeploymentValidationError
from .identifiers import validate_runtime_id
from .installs import SECRET_VALUE_FRAGMENTS
from .playbooks import PlaybookDefinition
from .resolver import CapabilityResolver, RuntimeRegistry


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
    for key in config:
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in SECRET_VALUE_FRAGMENTS) and not lowered.endswith("_ref"):
            raise DeploymentValidationError(
                "deployment.config_secret_value",
                "Playbook deployment config may contain references, but not secret-shaped values.",
                {"field": key},
            )
    return _json_safe(config)


@dataclass(frozen=True)
class DeploymentPolicy:
    allow_network: bool = False
    allowed_network_domains: tuple[str, ...] = field(default_factory=tuple)
    allow_mutations: bool = False
    allow_filesystem: bool = False
    allow_subprocess: bool = False
    require_approval_for_writes: bool = True
    approval_required_capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_network_domains", tuple(str(item) for item in self.allowed_network_domains))
        object.__setattr__(
            self,
            "approval_required_capabilities",
            tuple(str(item) for item in self.approval_required_capabilities),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_filesystem": self.allow_filesystem,
            "allow_mutations": self.allow_mutations,
            "allow_network": self.allow_network,
            "allow_subprocess": self.allow_subprocess,
            "allowed_network_domains": list(self.allowed_network_domains),
            "approval_required_capabilities": list(self.approval_required_capabilities),
            "require_approval_for_writes": self.require_approval_for_writes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeploymentPolicy:
        return cls(
            allow_network=bool(payload.get("allow_network", False)),
            allowed_network_domains=tuple(str(item) for item in payload.get("allowed_network_domains", ())),
            allow_mutations=bool(payload.get("allow_mutations", False)),
            allow_filesystem=bool(payload.get("allow_filesystem", False)),
            allow_subprocess=bool(payload.get("allow_subprocess", False)),
            require_approval_for_writes=bool(payload.get("require_approval_for_writes", True)),
            approval_required_capabilities=tuple(
                str(item) for item in payload.get("approval_required_capabilities", ())
            ),
        )


@dataclass(frozen=True)
class RequirementBinding:
    install_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "install_id", validate_runtime_id(self.install_id, field_name="binding.install_id"))

    def to_dict(self) -> dict[str, Any]:
        return {"install_id": self.install_id}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RequirementBinding:
        return cls(install_id=str(payload.get("install_id") or ""))


@dataclass(frozen=True)
class PlaybookDeployment:
    deployment_id: str
    playbook_id: str
    playbook_version: str
    workspace_id: str
    requirement_bindings: dict[str, RequirementBinding] = field(default_factory=dict)
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    policy: DeploymentPolicy = field(default_factory=DeploymentPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "deployment_id", validate_runtime_id(self.deployment_id, field_name="deployment_id"))
        object.__setattr__(self, "workspace_id", validate_runtime_id(self.workspace_id, field_name="workspace_id"))
        normalized: dict[str, RequirementBinding] = {}
        for slot, binding in self.requirement_bindings.items():
            normalized_slot = validate_runtime_id(slot, field_name="requirement_binding.slot")
            normalized[normalized_slot] = (
                binding if isinstance(binding, RequirementBinding) else RequirementBinding.from_dict(dict(binding))
            )
        object.__setattr__(self, "requirement_bindings", normalized)
        object.__setattr__(self, "config", _safe_config(self.config))
        object.__setattr__(
            self,
            "policy",
            self.policy if isinstance(self.policy, DeploymentPolicy) else DeploymentPolicy.from_dict(dict(self.policy)),
        )

    def binding_for(self, requirement_slot: str) -> RequirementBinding | None:
        return self.requirement_bindings.get(requirement_slot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": _json_safe(self.config),
            "deployment_id": self.deployment_id,
            "enabled": self.enabled,
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
            "policy": self.policy.to_dict(),
            "requirement_bindings": {
                slot: binding.to_dict() for slot, binding in sorted(self.requirement_bindings.items())
            },
            "workspace_id": self.workspace_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookDeployment:
        return cls(
            deployment_id=str(payload.get("deployment_id") or ""),
            playbook_id=str(payload.get("playbook_id") or ""),
            playbook_version=str(payload.get("playbook_version") or ""),
            workspace_id=str(payload.get("workspace_id") or ""),
            requirement_bindings={
                str(slot): RequirementBinding.from_dict(dict(binding))
                for slot, binding in dict(payload.get("requirement_bindings") or {}).items()
                if isinstance(binding, dict)
            },
            enabled=bool(payload.get("enabled", True)),
            config=dict(payload.get("config") or {}),
            policy=DeploymentPolicy.from_dict(dict(payload.get("policy") or {})),
        )


@dataclass(frozen=True)
class CapabilityReportEntry:
    requirement: str
    capability: str
    install_id: str = ""
    component_id: str = ""
    status: str = "OK"
    error_code: str = ""
    message: str = ""
    policy_decision: str = ""
    policy_reason: str = ""
    approval_required: bool = False

    def to_dict(self) -> dict[str, str]:
        return {
            "approval_required": str(self.approval_required),
            "capability": self.capability,
            "component_id": self.component_id,
            "error_code": self.error_code,
            "install_id": self.install_id,
            "message": self.message,
            "policy_decision": self.policy_decision,
            "policy_reason": self.policy_reason,
            "requirement": self.requirement,
            "status": self.status,
        }


@dataclass(frozen=True)
class DeploymentValidationResult:
    ok: bool
    entries: tuple[CapabilityReportEntry, ...]

    def failures(self) -> tuple[CapabilityReportEntry, ...]:
        return tuple(entry for entry in self.entries if entry.status != "OK")

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self.entries], "ok": self.ok}


def capability_report(
    playbook: PlaybookDefinition,
    deployment: PlaybookDeployment,
    registry: RuntimeRegistry,
    policy_engine: Any | None = None,
) -> DeploymentValidationResult:
    resolver = CapabilityResolver(registry)
    entries: list[CapabilityReportEntry] = []
    if not deployment.enabled:
        entries.append(
            CapabilityReportEntry(
                requirement="",
                capability="",
                status="ERROR",
                error_code="DEPLOYMENT_DISABLED",
                message="Deployment is disabled.",
            )
        )
    if deployment.playbook_id != playbook.playbook_id or deployment.playbook_version != playbook.version:
        entries.append(
            CapabilityReportEntry(
                requirement="",
                capability="",
                status="ERROR",
                error_code="PLAYBOOK_MISMATCH",
                message="Deployment does not target this playbook version.",
            )
        )
    for requirement_slot, requirement in sorted(playbook.requirements.items()):
        binding = deployment.binding_for(requirement_slot)
        if binding is None:
            for capability in requirement.capabilities:
                entries.append(
                    CapabilityReportEntry(
                        requirement=requirement_slot,
                        capability=capability,
                        status="ERROR",
                        error_code="MISSING_BINDING",
                        message="Requirement is not bound to an install.",
                    )
                )
            continue
        for capability in requirement.capabilities:
            try:
                resolved = resolver.resolve(install_id=binding.install_id, capability=capability)
            except CapabilityResolutionError as exc:
                error_code = "MISSING_CAPABILITY"
                if exc.code == "runtime.install_disabled":
                    error_code = "INSTALL_DISABLED"
                elif exc.code == "runtime.install_missing":
                    error_code = "INSTALL_MISSING"
                entries.append(
                    CapabilityReportEntry(
                        requirement=requirement_slot,
                        capability=capability,
                        install_id=binding.install_id,
                        status="ERROR",
                        error_code=error_code,
                        message=exc.user_message,
                    )
                )
            else:
                policy_decision = ""
                policy_reason = ""
                approval_required = False
                if policy_engine is not None:
                    from .events import EventEnvelope, EventSource
                    from .execution_context import ExecutionContext
                    from .plans import ExecutionPlanNode

                    context = ExecutionContext(
                        execution_id="policy_report",
                        deployment_id=deployment.deployment_id,
                        trigger_event=EventEnvelope(
                            event_type="runtime.policy.report",
                            source=EventSource(provider="runtime"),
                        ),
                    )
                    decision = policy_engine.evaluate(
                        execution_context=context,
                        plan_node=ExecutionPlanNode(
                            node_id="policy-report",
                            kind="capability",
                            requirement=requirement_slot,
                            capability=capability,
                            install_id=resolved.install.install_id,
                            component_id=resolved.component.component_id,
                            provider=resolved.component.provider,
                        ),
                    )
                    policy_decision = "ALLOW" if decision.allowed and not decision.required_approval else "APPROVAL"
                    if not decision.allowed:
                        policy_decision = "DENY"
                    policy_reason = decision.reason_code
                    approval_required = decision.required_approval
                entries.append(
                    CapabilityReportEntry(
                        requirement=requirement_slot,
                        capability=capability,
                        install_id=resolved.install.install_id,
                        component_id=resolved.component.component_id,
                        policy_decision=policy_decision,
                        policy_reason=policy_reason,
                        approval_required=approval_required,
                    )
                )
    return DeploymentValidationResult(ok=not any(entry.status != "OK" for entry in entries), entries=tuple(entries))


def validate_deployment(
    playbook: PlaybookDefinition,
    deployment: PlaybookDeployment,
    registry: RuntimeRegistry,
    policy_engine: Any | None = None,
) -> DeploymentValidationResult:
    result = capability_report(playbook, deployment, registry, policy_engine=policy_engine)
    if not result.ok:
        first = result.failures()[0]
        raise DeploymentValidationError(
            first.error_code,
            first.message or "Playbook deployment is invalid.",
            first.to_dict(),
        )
    denied = next((entry for entry in result.entries if entry.policy_decision == "DENY"), None)
    if denied is not None:
        raise DeploymentValidationError(
            denied.policy_reason,
            denied.message or "Playbook deployment is not permitted by runtime policy.",
            denied.to_dict(),
        )
    return result
