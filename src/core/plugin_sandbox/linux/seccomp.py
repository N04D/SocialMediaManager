"""Linux seccomp policy metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SECCOMP_PROFILES = {
    "python_plugin_base": [
        "ptrace",
        "mount",
        "umount2",
        "unshare",
        "setns",
        "bpf",
        "init_module",
        "finit_module",
        "delete_module",
        "reboot",
        "kexec_load",
        "open_by_handle_at",
        "process_vm_readv",
        "process_vm_writev",
        "keyctl",
        "add_key",
        "request_key",
    ],
    "channel_api_first": ["socket", "connect", "bind", "listen", "execveat"],
    "channel_browser_proxy": ["socket", "connect", "bind", "listen", "execveat"],
    "channel_metrics_read": ["socket", "connect", "bind", "listen", "execveat"],
}


def profile_checksum(name: str) -> str:
    payload = SECCOMP_PROFILES.get(name, [])
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def seccomp_status() -> str:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("Seccomp:"):
                return line.split(":", maxsplit=1)[1].strip()
    except OSError:
        return "unavailable"
    return "unknown"


__all__ = ["SECCOMP_PROFILES", "profile_checksum", "seccomp_status"]
