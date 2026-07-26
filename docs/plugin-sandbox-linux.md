# Linux Sandbox

Linux is the primary phase-20 production baseline. Required controls are `PR_SET_NO_NEW_PRIVS`, user, mount, PID, IPC, UTS, and network namespaces, private mount propagation, read-only code environment, minimal writable directories, isolated `/proc`, minimal `/dev`, seccomp, Landlock, direct network default-deny, rlimits, process group containment, and sandbox attestation.

cgroup v2 and Landlock network rules are defense-in-depth controls when available. If a required control is missing, community activation is blocked unless an explicit development override is active.

Phase 20.1 adds the host-owned Linux launcher. It first creates the user namespace, writes UID/GID maps, creates mount/PID/IPC/UTS/network namespaces, makes mount propagation private, mounts a sandbox `/proc` and minimal `/dev`, sets `no_new_privs`, drops ambient capabilities, then execs `venv-python -I -m plugin_host_runtime`.

Production readiness is true only when configured, detected, enforced, and verified controls all match. Kernel support alone is not enough; the namespace mapping probe, Landlock ABI probe, seccomp load probe, child-side attestation, and denial probes must pass.
