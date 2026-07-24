"""Plugin Sandbox Framework v0.1."""

from .attestation import build_attestation
from .compiler import SandboxPolicyCompiler
from .contracts import (
    PLUGIN_SANDBOX_ATTESTATION_CONTRACT_VERSION,
    PLUGIN_SANDBOX_FILESYSTEM_CONTRACT_VERSION,
    PLUGIN_SANDBOX_FRAMEWORK_VERSION,
    PLUGIN_SANDBOX_NETWORK_CONTRACT_VERSION,
    PLUGIN_SANDBOX_PLAN_CONTRACT_VERSION,
    PLUGIN_SANDBOX_PLATFORM_CONTRACT_VERSION,
    PLUGIN_SANDBOX_POLICY_CONTRACT_VERSION,
    PLUGIN_SANDBOX_SYSCALL_CONTRACT_VERSION,
    PLUGIN_SANDBOX_VIOLATION_CONTRACT_VERSION,
)
from .controller import UnsupportedPluginSandboxController, select_sandbox_controller
from .errors import (
    PluginSandboxActivationBlockedError,
    PluginSandboxError,
    PluginSandboxPlanError,
    PluginSandboxPolicyError,
    PluginSandboxUnavailableError,
    PluginSandboxVerificationError,
    PluginSandboxViolationError,
)
from .integrity import PluginSandboxIntegrityService
from .models import (
    PluginHostProcessSpec,
    PluginSandboxAttestation,
    PluginSandboxHealth,
    PluginSandboxPlan,
    PluginSandboxPolicy,
    PluginSandboxViolation,
    SandboxCompilationContext,
    SandboxedProcess,
    SandboxPlatformCapability,
    SandboxPreparationResult,
)
from .violations import PluginSandboxViolationStore, classify_violation

__all__ = [
    "PLUGIN_SANDBOX_ATTESTATION_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_FILESYSTEM_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_FRAMEWORK_VERSION",
    "PLUGIN_SANDBOX_NETWORK_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_PLAN_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_PLATFORM_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_POLICY_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_SYSCALL_CONTRACT_VERSION",
    "PLUGIN_SANDBOX_VIOLATION_CONTRACT_VERSION",
    "PluginHostProcessSpec",
    "PluginSandboxActivationBlockedError",
    "PluginSandboxAttestation",
    "PluginSandboxError",
    "PluginSandboxHealth",
    "PluginSandboxIntegrityService",
    "PluginSandboxPlan",
    "PluginSandboxPlanError",
    "PluginSandboxPolicy",
    "PluginSandboxPolicyError",
    "PluginSandboxUnavailableError",
    "PluginSandboxVerificationError",
    "PluginSandboxViolation",
    "PluginSandboxViolationError",
    "PluginSandboxViolationStore",
    "SandboxCompilationContext",
    "SandboxPlatformCapability",
    "SandboxPolicyCompiler",
    "SandboxPreparationResult",
    "SandboxedProcess",
    "UnsupportedPluginSandboxController",
    "build_attestation",
    "classify_violation",
    "select_sandbox_controller",
]
