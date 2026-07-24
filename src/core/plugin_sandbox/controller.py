"""Sandbox controller selection and base implementation."""

from __future__ import annotations

import platform
import subprocess
import uuid
from pathlib import Path
from typing import Protocol

from .attestation import build_attestation
from .compiler import SandboxPolicyCompiler
from .errors import PluginSandboxActivationBlockedError
from .models import (
    PluginHostProcessSpec,
    PluginSandboxAttestation,
    PluginSandboxPlan,
    PluginSandboxPolicy,
    SandboxCompilationContext,
    SandboxedProcess,
    SandboxPlatformCapability,
    SandboxPreparationResult,
)


class PluginSandboxController(Protocol):
    def inspect_platform(self) -> SandboxPlatformCapability: ...

    def compile_plan(self, policy: PluginSandboxPolicy, context: SandboxCompilationContext) -> PluginSandboxPlan: ...

    def prepare(self, plan: PluginSandboxPlan) -> SandboxPreparationResult: ...

    def launch(self, plan: PluginSandboxPlan, process_spec: PluginHostProcessSpec) -> SandboxedProcess: ...

    def attest(self, process: SandboxedProcess, plan: PluginSandboxPlan) -> PluginSandboxAttestation: ...

    def terminate(self, process: SandboxedProcess) -> None: ...


class UnsupportedPluginSandboxController:
    def __init__(self, *, development_override: bool = False) -> None:
        self.development_override = development_override
        self.compiler = SandboxPolicyCompiler()

    def inspect_platform(self) -> SandboxPlatformCapability:
        return SandboxPlatformCapability(
            platform=platform.system().lower() or "unknown",
            architecture=platform.machine(),
            supported=False,
            production_ready=False,
            available_controls=[],
            missing_controls=["sandbox_attestation"],
            status="sandbox_unavailable",
            safe_error_code="plugin_sandbox.platform.unsupported",
            warnings=["Unsupported platforms fail closed for community plugins."],
        )

    def compile_plan(self, policy: PluginSandboxPolicy, context: SandboxCompilationContext) -> PluginSandboxPlan:
        return self.compiler.compile_plan(policy, context, self.inspect_platform())

    def prepare(self, plan: PluginSandboxPlan) -> SandboxPreparationResult:
        return SandboxPreparationResult(
            plan.id, "unsupported", [], list(plan.required_controls), ["Sandbox unavailable."]
        )

    def launch(self, plan: PluginSandboxPlan, process_spec: PluginHostProcessSpec) -> SandboxedProcess:
        if not self.development_override:
            raise PluginSandboxActivationBlockedError(
                "plugin_sandbox.activation.blocked", "OS sandbox is unavailable and production activation is blocked."
            )
        process = subprocess.Popen(
            process_spec.argv,
            stdin=process_spec.stdin,
            stdout=process_spec.stdout,
            stderr=process_spec.stderr,
            cwd=process_spec.cwd,
            env=process_spec.env,
            shell=False,
            close_fds=True,
        )
        return SandboxedProcess(process, f"proc_{uuid.uuid4().hex}", plan.id, "development_override", [])

    def attest(self, process: SandboxedProcess, plan: PluginSandboxPlan) -> PluginSandboxAttestation:
        return build_attestation(
            plan=plan,
            process=process,
            host_id="unsupported",
            platform_evidence={"controller": "unsupported"},
            missing_controls=list(plan.required_controls),
            development_override=self.development_override,
            warnings=["Development override is unsandboxed/degraded."],
        )

    def terminate(self, process: SandboxedProcess) -> None:
        process.process.terminate()
        try:
            process.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.process.kill()
            process.process.wait(timeout=2)


def select_sandbox_controller(*, development_override: bool = False) -> PluginSandboxController:
    system = platform.system().lower()
    if system == "linux":
        from .linux.controller import LinuxPluginSandboxController

        return LinuxPluginSandboxController(development_override=development_override)
    if system == "windows":
        from .windows.controller import WindowsPluginSandboxController

        return WindowsPluginSandboxController(development_override=development_override)
    if system == "darwin":
        from .macos.controller import MacOSPluginSandboxController

        return MacOSPluginSandboxController(development_override=development_override)
    return UnsupportedPluginSandboxController(development_override=development_override)


def safe_path_summary(path: str | Path) -> str:
    text = str(path)
    for marker in ["content", "drafts", ".ssh", ".gnupg"]:
        if marker in text:
            return marker
    return Path(text).name or "path"


__all__ = [
    "PluginSandboxController",
    "UnsupportedPluginSandboxController",
    "safe_path_summary",
    "select_sandbox_controller",
]
