# Linux Sandbox

Linux is the primary phase-20 production baseline. Required controls are `PR_SET_NO_NEW_PRIVS`, user, mount, PID, IPC, UTS, and network namespaces, private mount propagation, read-only code environment, minimal writable directories, isolated `/proc`, minimal `/dev`, seccomp, Landlock, direct network default-deny, rlimits, process group containment, and sandbox attestation.

cgroup v2 and Landlock network rules are defense-in-depth controls when available. If a required control is missing, community activation is blocked unless an explicit development override is active.
