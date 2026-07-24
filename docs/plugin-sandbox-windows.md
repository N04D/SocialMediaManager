# Windows Sandbox

Windows production containment requires AppContainer or less-privileged AppContainer identity, restricted primary token, minimal privileges, Job Object with kill-on-close, process tree containment, process count and memory limits, plugin-scoped filesystem ACLs, no direct network capability, and sandbox attestation.

The controller, policy, and fail-closed attestation gate are present. If required Windows APIs are unavailable or verification fails, activation is blocked.
