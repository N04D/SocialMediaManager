# Plugin Sandbox Framework v0.1

Phase 20 adds `src/core/plugin_sandbox` as the OS-level isolation layer for external plugin hosts. It does not change Plugin SDK v1, Plugin Distribution v0.1, Plugin Host v0.1, or the Browser, Media, Content, Execution, Scheduling, and Analytics framework contracts.

Contract versions:

- `PLUGIN_SANDBOX_FRAMEWORK_VERSION = "0.1.0"`
- `PLUGIN_SANDBOX_POLICY_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_PLAN_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_ATTESTATION_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_FILESYSTEM_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_NETWORK_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_SYSCALL_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_VIOLATION_CONTRACT_VERSION = "1.0"`
- `PLUGIN_SANDBOX_PLATFORM_CONTRACT_VERSION = "1.0"`

Only use `OS sandbox enforced` when the platform controller verifies every required control. Otherwise report `sandbox_unavailable`, `sandbox_incomplete`, `sandbox_degraded`, `sandbox_verification_failed`, or `development_override`.
