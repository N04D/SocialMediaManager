"""macOS sandbox controller with official App Sandbox gate."""

from __future__ import annotations

import platform

from ..controller import UnsupportedPluginSandboxController
from ..models import SandboxPlatformCapability
from ..policies import MACOS_REQUIRED_CONTROLS
from .app_sandbox import app_sandbox_entitlement_active
from .entitlements import minimal_entitlements_present
from .helper_verification import signed_helper_verified


class MacOSPluginSandboxController(UnsupportedPluginSandboxController):
    def inspect_platform(self) -> SandboxPlatformCapability:
        available = []
        if app_sandbox_entitlement_active():
            available.append("app_sandbox_entitlement")
        if minimal_entitlements_present():
            available.append("helper_entitlements")
        if signed_helper_verified():
            available.append("signed_helper")
        missing = [control for control in MACOS_REQUIRED_CONTROLS if control not in available]
        return SandboxPlatformCapability(
            platform="darwin",
            architecture=platform.machine(),
            supported=True,
            production_ready=not missing,
            available_controls=available,
            missing_controls=missing,
            status="OS sandbox enforced" if not missing else "sandbox_unavailable",
            safe_error_code="" if not missing else "plugin_sandbox.macos.unavailable",
            warnings=[
                "macOS production activation requires official App Sandbox signing, entitlements, and helper attestation."
            ]
            if missing
            else [],
        )


__all__ = ["MacOSPluginSandboxController"]
