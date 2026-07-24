"""Windows sandbox controller with fail-closed production policy."""

from __future__ import annotations

import platform

from ..controller import UnsupportedPluginSandboxController
from ..models import SandboxPlatformCapability
from ..policies import WINDOWS_REQUIRED_CONTROLS
from .appcontainer import appcontainer_available
from .job_object import job_object_available
from .restricted_token import restricted_token_available


class WindowsPluginSandboxController(UnsupportedPluginSandboxController):
    def inspect_platform(self) -> SandboxPlatformCapability:
        available = []
        if appcontainer_available():
            available.append("appcontainer")
        if restricted_token_available():
            available.append("restricted_token")
        if job_object_available():
            available.append("job_object")
        missing = [control for control in WINDOWS_REQUIRED_CONTROLS if control not in available]
        return SandboxPlatformCapability(
            platform="windows",
            architecture=platform.machine(),
            supported=True,
            production_ready=not missing,
            available_controls=available,
            missing_controls=missing,
            status="OS sandbox enforced" if not missing else "sandbox_incomplete",
            safe_error_code="" if not missing else "plugin_sandbox.windows.incomplete",
            warnings=[
                "Windows production activation is blocked until AppContainer, restricted token, Job Object, ACL and network checks attest."
            ]
            if missing
            else [],
        )


__all__ = ["WindowsPluginSandboxController"]
