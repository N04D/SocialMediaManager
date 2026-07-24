"""Read-only sandbox health and integrity scans."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .contracts import PLUGIN_SANDBOX_FRAMEWORK_VERSION
from .controller import select_sandbox_controller
from .models import PluginSandboxHealth, PluginSandboxPlan, SandboxCompilationContext, utc_now
from .violations import PluginSandboxViolationStore


class PluginSandboxIntegrityService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.violations = PluginSandboxViolationStore(self.root / "violations")

    def health(self) -> PluginSandboxHealth:
        capability = select_sandbox_controller().inspect_platform()
        violations = self.violations.list()
        severe = [item for item in violations if item.severity in {"high", "critical"}]
        return PluginSandboxHealth(
            platform=capability.platform,
            controller_status=capability.status,
            supported=capability.supported,
            production_ready=capability.production_ready,
            required_controls=capability.available_controls + capability.missing_controls,
            active_controls=capability.available_controls,
            missing_controls=capability.missing_controls,
            degraded_controls=[] if capability.production_ready else capability.missing_controls,
            active_sandboxed_hosts=0,
            unsandboxed_development_hosts=0,
            violation_count=len(violations),
            severe_violation_count=len(severe),
            latest_integrity_scan=utc_now(),
            safe_error_code=capability.safe_error_code,
            warnings=capability.warnings,
        )

    def scan(self, plans: list[PluginSandboxPlan] | None = None) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        for plan in plans or []:
            if plan.expected_attestation.get("status") != "enforced":
                findings.append(
                    {
                        "code": "plugin_sandbox.integrity.plan_incomplete",
                        "severity": "high",
                        "plugin_id": plan.plugin_id,
                        "safe_message": "Sandbox plan is missing required controls.",
                    }
                )
        return findings

    def to_public(self) -> dict[str, object]:
        return {
            "framework_version": PLUGIN_SANDBOX_FRAMEWORK_VERSION,
            "health": asdict(self.health()),
            "findings": self.scan(),
        }


def context_from_install_record(row: dict[str, object], environment_checksum: str = "") -> SandboxCompilationContext:
    return SandboxCompilationContext(
        install_record_id=str(row.get("id") or ""),
        environment_id=f"{row.get('plugin_id')}=={row.get('plugin_version')}",
        artifact_checksum=str(row.get("artifact_sha256") or ""),
        environment_checksum=environment_checksum,
        distribution_status=str(row.get("distribution_status") or "community"),
    )


__all__ = ["PluginSandboxIntegrityService", "context_from_install_record"]
