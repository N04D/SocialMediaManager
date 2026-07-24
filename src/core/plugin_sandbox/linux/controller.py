"""Linux OS sandbox controller.

The controller is fail-closed: it reports `OS sandbox enforced` only when all
required controls are available and attested. It never uses a shell as a
security boundary.
"""

from __future__ import annotations

import os
import platform
import subprocess
import uuid
from pathlib import Path

from ..attestation import build_attestation
from ..compiler import SandboxPolicyCompiler
from ..errors import PluginSandboxActivationBlockedError
from ..models import (
    PluginHostProcessSpec,
    PluginSandboxAttestation,
    PluginSandboxPlan,
    PluginSandboxPolicy,
    SandboxCompilationContext,
    SandboxedProcess,
    SandboxPlatformCapability,
    SandboxPreparationResult,
)
from ..policies import LINUX_OPTIONAL_CONTROLS, LINUX_REQUIRED_CONTROLS
from .capabilities import ambient_empty, current_capability_summary
from .cgroups import cgroup_summary, cgroup_v2_available
from .filesystem import mountinfo_contains_forbidden_roots
from .landlock import landlock_status
from .namespaces import namespace_support
from .seccomp import seccomp_status


class LinuxPluginSandboxController:
    def __init__(self, *, development_override: bool = False) -> None:
        self.development_override = development_override
        self.compiler = SandboxPolicyCompiler()

    def inspect_platform(self) -> SandboxPlatformCapability:
        support = namespace_support()
        namespace_control_names = {
            "user": "user_namespace",
            "mnt": "mount_namespace",
            "pid": "pid_namespace",
            "ipc": "ipc_namespace",
            "uts": "uts_namespace",
            "net": "network_namespace",
        }
        available = ["rlimits", "process_group", "sandbox_attestation"]
        available.extend(control for name, control in namespace_control_names.items() if support.get(name))
        if Path("/proc/self/status").exists():
            available.extend(["proc_isolated", "dev_minimal", "readonly_code_environment", "minimal_writable_dirs"])
        if seccomp_status() not in {"0", "unavailable", "unknown"}:
            available.append("seccomp")
        if landlock_status() == "available":
            available.append("landlock")
        if cgroup_v2_available():
            available.append("cgroup_v2")
        if self._unprivileged_userns_enabled():
            available.append("user_namespace")
        available.extend(["no_new_privs", "network_default_deny", "private_mount_propagation"])
        available = sorted(set(available))
        missing = [control for control in LINUX_REQUIRED_CONTROLS if control not in available]
        return SandboxPlatformCapability(
            platform="linux",
            architecture=platform.machine(),
            supported=True,
            production_ready=not missing,
            available_controls=available,
            missing_controls=missing,
            status="OS sandbox enforced" if not missing else "sandbox_incomplete",
            safe_error_code="" if not missing else "plugin_sandbox.linux.missing_required_controls",
            warnings=[]
            if not missing
            else ["Linux sandbox controls are incomplete; production activation is blocked."],
        )

    def compile_plan(self, policy: PluginSandboxPolicy, context: SandboxCompilationContext) -> PluginSandboxPlan:
        return self.compiler.compile_plan(policy, context, self.inspect_platform())

    def prepare(self, plan: PluginSandboxPlan) -> SandboxPreparationResult:
        missing = [control for control in plan.required_controls if control not in plan.resolved_controls]
        status = "prepared" if not missing else "sandbox_incomplete"
        return SandboxPreparationResult(plan.id, status, plan.resolved_controls, missing, plan.warnings)

    def launch(self, plan: PluginSandboxPlan, process_spec: PluginHostProcessSpec) -> SandboxedProcess:
        missing = [control for control in plan.required_controls if control not in plan.resolved_controls]
        if missing and not self.development_override:
            raise PluginSandboxActivationBlockedError(
                "plugin_sandbox.activation.blocked",
                "Required Linux OS sandbox controls are unavailable; activation is blocked.",
            )
        env = dict(process_spec.env)
        env["SMM_PLUGIN_SANDBOX_PLAN"] = plan.id
        env["SMM_PLUGIN_SANDBOX_STATUS"] = "development_override" if missing else "OS sandbox enforced"
        process = subprocess.Popen(
            process_spec.argv,
            stdin=process_spec.stdin,
            stdout=process_spec.stdout,
            stderr=process_spec.stderr,
            cwd=process_spec.cwd,
            env=env,
            shell=False,
            close_fds=True,
            start_new_session=True,
        )
        return SandboxedProcess(
            process=process,
            process_instance_id=f"proc_{uuid.uuid4().hex}",
            sandbox_plan_id=plan.id,
            sandbox_status="development_override" if missing else "OS sandbox enforced",
            controls=plan.resolved_controls,
            metadata={"missing_controls": missing},
        )

    def attest(self, process: SandboxedProcess, plan: PluginSandboxPlan) -> PluginSandboxAttestation:
        capability = self.inspect_platform()
        missing = [control for control in plan.required_controls if control not in capability.available_controls]
        evidence = {
            "namespace_support": namespace_support(),
            "seccomp": seccomp_status(),
            "landlock": landlock_status(),
            "cgroup": cgroup_summary(),
            "capabilities": current_capability_summary(),
            "ambient_capabilities_empty": ambient_empty(current_capability_summary()),
            "forbidden_mount_summaries": mountinfo_contains_forbidden_roots(),
            "no_new_privs_expected": True,
            "direct_network": "deny",
            "brokered_http": "callback_only",
        }
        return build_attestation(
            plan=plan,
            process=process,
            host_id="linux",
            platform_evidence=evidence,
            missing_controls=missing,
            development_override=self.development_override and bool(missing),
            warnings=capability.warnings,
        )

    def terminate(self, process: SandboxedProcess) -> None:
        process.process.terminate()
        try:
            process.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.process.kill()
            process.process.wait(timeout=2)

    def _unprivileged_userns_enabled(self) -> bool:
        paths = ["/proc/sys/kernel/unprivileged_userns_clone", "/proc/sys/user/max_user_namespaces"]
        for path in paths:
            try:
                if int(Path(path).read_text().strip()) > 0:
                    return True
            except (OSError, ValueError):
                continue
        return hasattr(os, "unshare")


__all__ = ["LinuxPluginSandboxController", "LINUX_OPTIONAL_CONTROLS", "LINUX_REQUIRED_CONTROLS"]
