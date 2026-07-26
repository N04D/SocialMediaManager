# Linux Filesystem Sandbox

The sandbox filesystem is allowlist-based. Read-only surfaces are the plugin virtual environment, host runtime, Python standard library, minimal system libraries, and immutable manifest metadata. Writable surfaces are plugin-scoped temp and active call-scoped transfers.

The repository root, user home, `.ssh`, `.gnupg`, browser profiles, database files, `content/`, `drafts/`, other plugin installs, other plugin state, Docker sockets, SSH-agent sockets, display sockets, D-Bus, and system sockets must not be visible.

The minimal `/dev` contains only `/dev/null`, `/dev/zero`, `/dev/random`, and `/dev/urandom`.

Writable mounts are modeled as `noexec`, `nosuid`, and `nodev`.

Phase 20.1 uses Landlock as the final filesystem enforcement layer before external plugin import. Runtime and environment paths are read/execute only; plugin temp and call-scoped transfers are the only writable paths. Denial probes verify that repository, home, `content/`, `drafts/`, code writes, symlink escapes, and hardlink escapes do not unexpectedly succeed.
