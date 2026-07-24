"""Compile plugin permissions into immutable sandbox policies and plans."""

from __future__ import annotations

import hashlib
import json
import platform
import uuid

from .errors import PluginSandboxPolicyError
from .models import (
    PluginSandboxPlan,
    PluginSandboxPolicy,
    SandboxCompilationContext,
    SandboxPlatformCapability,
    default_expiry,
    utc_now,
)
from .policies import (
    LINUX_OPTIONAL_CONTROLS,
    LINUX_REQUIRED_CONTROLS,
    MACOS_REQUIRED_CONTROLS,
    SENSITIVE_DENY_PATH_SUMMARIES,
    UNSUPPORTED_DIRECT_PERMISSIONS,
    WINDOWS_REQUIRED_CONTROLS,
)


def _checksum(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SandboxPolicyCompiler:
    def build_policy(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        distribution_status: str,
        permissions: list[str],
        capabilities: list[str],
        platform_name: str | None = None,
        development_override: bool = False,
    ) -> PluginSandboxPolicy:
        unsupported = sorted(set(permissions) & UNSUPPORTED_DIRECT_PERMISSIONS)
        if unsupported:
            raise PluginSandboxPolicyError(
                "plugin_sandbox.permission.unsupported",
                "Plugin requests direct host capabilities that phase 20 does not support.",
            )
        if "subprocess" in permissions and distribution_status == "community":
            raise PluginSandboxPolicyError(
                "plugin_sandbox.permission.subprocess_unsupported",
                "Community channel plugins cannot request subprocess permission in phase 20.",
            )
        platform_id = platform_name or platform.system().lower()
        required, optional = self._controls_for_platform(platform_id)
        filesystem_policy = {
            "mode": "allowlist",
            "readonly": ["plugin_environment", "host_runtime", "python_stdlib", "manifest_metadata"],
            "writable": ["plugin_temp", "call_scoped_transfers"],
            "denied": SENSITIVE_DENY_PATH_SUMMARIES,
            "no_exec_writable": True,
            "no_suid": True,
            "no_device": True,
        }
        network_policy = {"direct": "deny", "brokered_http": "allowed" if "outbound_network" in permissions else "deny"}
        syscall_policy = {
            "profile": "channel_browser_proxy" if "browser_session" in permissions else "channel_api_first",
            "blocked_categories": [
                "kernel_module",
                "reboot",
                "mount_after_setup",
                "namespace_after_setup",
                "ptrace",
                "process_memory",
                "bpf",
                "keyring",
                "clock_modification",
                "privileged_io",
                "kexec",
                "arbitrary_spawn",
            ],
        }
        payload = {
            "plugin_id": plugin_id,
            "plugin_version": plugin_version,
            "distribution_status": distribution_status,
            "permissions": sorted(permissions),
            "capabilities": sorted(capabilities),
            "platform": platform_id,
            "required": required,
            "filesystem": filesystem_policy,
            "network": network_policy,
            "syscall": syscall_policy,
        }
        return PluginSandboxPolicy(
            id=f"policy_{uuid.uuid4().hex}",
            version="1.0",
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            distribution_status=distribution_status,
            permissions=sorted(permissions),
            capabilities=sorted(capabilities),
            platform=platform_id,
            enforcement_mode="development_only" if development_override else "required",
            filesystem_policy=filesystem_policy,
            network_policy=network_policy,
            syscall_policy=syscall_policy,
            process_policy={"subprocess": "deny", "threads": "allow", "fork_bomb": "deny"},
            ipc_policy={"host_unix_sockets": "deny", "stdio_rpc": "allow"},
            identity_policy={"no_new_privs": True, "drop_capabilities": True},
            resource_policy_id="plugin_host_resource_policy_v1",
            required_controls=required,
            optional_controls=optional,
            failure_policy="fail_closed",
            development_override_allowed=True,
            checksum=_checksum(payload),
            created_at=utc_now(),
            metadata={"direct_network": "unsupported", "outbound_network": "brokered_http_only"},
        )

    def compile_plan(
        self, policy: PluginSandboxPolicy, context: SandboxCompilationContext, capability: SandboxPlatformCapability
    ) -> PluginSandboxPlan:
        resolved = [
            control
            for control in policy.required_controls + policy.optional_controls
            if control in capability.available_controls
        ]
        missing = [control for control in policy.required_controls if control not in capability.available_controls]
        if missing and policy.enforcement_mode == "required":
            warnings = [f"missing required controls: {', '.join(missing)}"]
        else:
            warnings = []
        return PluginSandboxPlan(
            id=f"plan_{uuid.uuid4().hex}",
            policy_id=policy.id,
            plugin_id=policy.plugin_id,
            plugin_version=policy.plugin_version,
            install_record_id=context.install_record_id,
            environment_id=context.environment_id,
            platform=capability.platform,
            architecture=capability.architecture,
            required_controls=list(policy.required_controls),
            resolved_controls=resolved,
            filesystem_mounts=[
                {"name": "plugin_environment", "mode": "ro"},
                {"name": "host_runtime", "mode": "ro"},
                {"name": "plugin_temp", "mode": "rw,noexec,nosuid,nodev"},
                {"name": "call_scoped_transfers", "mode": "rw,noexec,nosuid,nodev"},
            ],
            filesystem_rules=[policy.filesystem_policy],
            network_rules=[policy.network_policy],
            syscall_rules=[policy.syscall_policy],
            process_rules=[policy.process_policy],
            identity_rules=[policy.identity_policy],
            resource_rules=[{"policy": policy.resource_policy_id}],
            expected_attestation={"missing_controls": missing, "status": "enforced" if not missing else "incomplete"},
            policy_checksum=policy.checksum,
            environment_checksum=context.environment_checksum,
            artifact_checksum=context.artifact_checksum,
            created_at=utc_now(),
            expires_at=default_expiry(),
            warnings=warnings,
        )

    def _controls_for_platform(self, platform_id: str) -> tuple[list[str], list[str]]:
        if platform_id == "linux":
            return list(LINUX_REQUIRED_CONTROLS), list(LINUX_OPTIONAL_CONTROLS)
        if platform_id == "windows":
            return list(WINDOWS_REQUIRED_CONTROLS), []
        if platform_id == "darwin":
            return list(MACOS_REQUIRED_CONTROLS), []
        return ["sandbox_attestation"], []


__all__ = ["SandboxPolicyCompiler"]
