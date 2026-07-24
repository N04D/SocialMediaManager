# Sandbox Violations

`PluginSandboxViolation` stores only safe summaries: plugin and host identity, platform and control, operation and action, blocked status, severity, safe resource summary, optional syscall, network, filesystem summaries, call context and execution attempt references, and mutation state.

Never store full paths, secrets, content bodies, HTTP bodies, tokens, syscall argument dumps, or raw security descriptors.

Severity categories are `expected_denial`, `policy_violation`, `escape_attempt`, `broker_bypass_attempt`, `resource_limit`, `configuration_error`, `platform_failure`, and `unknown`.
