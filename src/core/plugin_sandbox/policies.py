"""Sandbox policy constants and permission mapping."""

from __future__ import annotations

LINUX_REQUIRED_CONTROLS = [
    "no_new_privs",
    "user_namespace",
    "uid_gid_mapping",
    "mount_namespace",
    "pid_namespace",
    "ipc_namespace",
    "uts_namespace",
    "network_namespace",
    "private_mount_propagation",
    "readonly_code_environment",
    "minimal_writable_dirs",
    "proc_isolated",
    "dev_minimal",
    "seccomp",
    "landlock",
    "network_default_deny",
    "rlimits",
    "process_group",
    "sandbox_attestation",
]

LINUX_OPTIONAL_CONTROLS = ["cgroup_v2", "landlock_network"]

WINDOWS_REQUIRED_CONTROLS = [
    "appcontainer",
    "restricted_token",
    "job_object",
    "kill_on_job_close",
    "filesystem_acl",
    "network_default_deny",
    "process_tree_containment",
    "sandbox_attestation",
]

MACOS_REQUIRED_CONTROLS = [
    "code_signed_host",
    "app_sandbox_entitlement",
    "signed_helper",
    "helper_entitlements",
    "sandbox_inheritance_or_xpc",
    "sandbox_attestation",
]

UNSUPPORTED_DIRECT_PERMISSIONS = {
    "filesystem_all",
    "network_all",
    "home_access",
    "host_process_access",
    "kernel_access",
    "device_access",
    "arbitrary_subprocess",
    "direct_network",
}

BROKER_PERMISSION_MAP = {
    "outbound_network": ["host.http.request"],
    "browser_session": ["host.browser.open_session", "host.browser.invoke", "host.browser.close_session"],
    "secret_storage": ["host.secret.put", "host.secret.get", "host.secret.revoke", "host.secret.has"],
    "media_read": ["host.media.materialize"],
    "media_materialization": ["host.media.materialize", "host.media.release"],
    "analytics_ingestion": ["host.analytics.ingest"],
    "execution_reporting": [
        "host.execution.report_phase",
        "host.execution.report_mutation_state",
        "host.execution.report_remote_ack",
        "host.execution.report_verification",
        "host.execution.report_cleanup",
    ],
    "account_configuration": ["host.state.get", "host.state.put", "host.state.delete", "host.state.compare_and_set"],
}

SENSITIVE_DENY_PATH_SUMMARIES = [
    "home",
    "repository",
    "content",
    "drafts",
    ".ssh",
    ".gnupg",
    "browserprofiles",
    "databasefiles",
    "docker.sock",
    "ssh-agent",
]


__all__ = [
    "BROKER_PERMISSION_MAP",
    "LINUX_OPTIONAL_CONTROLS",
    "LINUX_REQUIRED_CONTROLS",
    "MACOS_REQUIRED_CONTROLS",
    "SENSITIVE_DENY_PATH_SUMMARIES",
    "UNSUPPORTED_DIRECT_PERMISSIONS",
    "WINDOWS_REQUIRED_CONTROLS",
]
