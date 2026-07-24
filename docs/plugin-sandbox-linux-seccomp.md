# Linux Seccomp

Phase 20 defines versioned seccomp profiles: `python_plugin_base`, `channel_api_first`, `channel_browser_proxy`, and `channel_metrics_read`.

Profiles block privileged syscall categories such as kernel module loading, reboot, mount changes after setup, namespace changes after setup, `ptrace`, process memory access, BPF program loading, keyrings, privileged I/O, kexec, and arbitrary process spawning.

Profiles must not claim enforcement when the platform cannot verify seccomp availability.
