"""Sandbox attestation helpers."""

from __future__ import annotations

import hashlib
import json
import uuid

from .models import PluginSandboxAttestation, PluginSandboxPlan, SandboxedProcess, default_expiry, utc_now


def checksum_attestation_inputs(plan: PluginSandboxPlan) -> str:
    return hashlib.sha256(json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_attestation(
    *,
    plan: PluginSandboxPlan,
    process: SandboxedProcess,
    host_id: str,
    platform_evidence: dict[str, object],
    missing_controls: list[str],
    warnings: list[str] | None = None,
    development_override: bool = False,
) -> PluginSandboxAttestation:
    status = "development_override" if development_override else ("enforced" if not missing_controls else "incomplete")
    return PluginSandboxAttestation(
        id=f"att_{uuid.uuid4().hex}",
        sandbox_plan_id=plan.id,
        plugin_host_id=host_id,
        process_instance_id=process.process_instance_id,
        platform=plan.platform,
        enforcement_status=status,
        enforced_controls=[control for control in plan.required_controls if control not in missing_controls],
        missing_controls=missing_controls,
        filesystem_status="isolated" if "readonly_code_environment" not in missing_controls else "incomplete",
        network_status="default_deny" if "network_default_deny" not in missing_controls else "incomplete",
        syscall_status="restricted" if "seccomp" not in missing_controls else "incomplete",
        process_status="isolated" if "pid_namespace" not in missing_controls else "incomplete",
        identity_status="restricted" if "no_new_privs" not in missing_controls else "incomplete",
        resource_status="limited" if "rlimits" not in missing_controls else "incomplete",
        platform_evidence=platform_evidence,
        policy_checksum=plan.policy_checksum,
        environment_checksum=plan.environment_checksum,
        process_reference=str(getattr(process.process, "pid", "")),
        attested_at=utc_now(),
        expires_at=default_expiry(hours=1),
        status=status,
        warnings=warnings or [],
    )


__all__ = ["build_attestation", "checksum_attestation_inputs"]
