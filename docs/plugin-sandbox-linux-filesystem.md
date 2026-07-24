# Linux Filesystem Sandbox

The sandbox filesystem is allowlist-based. Read-only surfaces are the plugin virtual environment, host runtime, Python standard library, minimal system libraries, and immutable manifest metadata. Writable surfaces are plugin-scoped temp and active call-scoped transfers.

The repository root, user home, `.ssh`, `.gnupg`, browser profiles, database files, `content/`, `drafts/`, other plugin installs, other plugin state, Docker sockets, SSH-agent sockets, display sockets, D-Bus, and system sockets must not be visible.

Writable mounts are modeled as `noexec`, `nosuid`, and `nodev`.
