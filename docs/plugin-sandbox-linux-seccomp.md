# Linux Seccomp

Phase 20 defines versioned seccomp profiles: `python_plugin_base`, `channel_api_first`, `channel_browser_proxy`, and `channel_metrics_read`.

Profiles block privileged syscall categories such as kernel module loading, reboot, mount changes after setup, namespace changes after setup, `ptrace`, process memory access, BPF program loading, keyrings, privileged I/O, kexec, and arbitrary process spawning.

Profiles must not claim enforcement when the platform cannot verify seccomp availability.

Phase 20.1 loads the filter through libseccomp from host-owned code before external plugin import. The implementation uses a restrictive denylist over an allow-default profile so Python runtime and threading continue to work. Denied syscalls include `ptrace`, `process_vm_readv`, `process_vm_writev`, `mount`, `umount2`, `setns`, `unshare`, `bpf`, keyring operations, kernel module operations, reboot/kexec, swap operations, filesystem handle APIs, and `execve`/`execveat`.

`seccomp_status` must read mode `2` from `/proc/self/status` for verified enforcement.
