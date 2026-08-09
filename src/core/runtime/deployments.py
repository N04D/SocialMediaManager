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

    def binding_for(self, requirement_slot: str) -> RequirementBinding | None:
        return self.requirement_bindings.get(requirement_slot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": _json_safe(self.config),
            "deployment_id": self.deployment_id,
            "enabled": self.enabled,
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
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

    def to_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "component_id": self.component_id,
            "error_code": self.error_code,
            "install_id": self.install_id,
            "message": self.message,
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
    playbook: PlaybookDefinition, deployment: PlaybookDeployment, registry: RuntimeRegistry
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
                entries.append(
                    CapabilityReportEntry(
                        requirement=requirement_slot,
                        capability=capability,
                        install_id=resolved.install.install_id,
                        component_id=resolved.component.component_id,
                    )
                )
    return DeploymentValidationResult(ok=not any(entry.status != "OK" for entry in entries), entries=tuple(entries))


def validate_deployment(
    playbook: PlaybookDefinition, deployment: PlaybookDeployment, registry: RuntimeRegistry
) -> DeploymentValidationResult:
    result = capability_report(playbook, deployment, registry)
    if not result.ok:
        first = result.failures()[0]
        raise DeploymentValidationError(
            first.error_code,
            first.message or "Playbook deployment is invalid.",
            first.to_dict(),
        )
    return result
