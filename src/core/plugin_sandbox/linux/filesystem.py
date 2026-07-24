"""Linux sandbox filesystem policy helpers."""

from __future__ import annotations

from pathlib import Path

DENIED_HOST_PATHS = ["content", "drafts", ".ssh", ".gnupg", "docker.sock", "SSH_AUTH_SOCK"]


def mountinfo_contains_forbidden_roots(mountinfo: str | None = None) -> list[str]:
    text = mountinfo
    if text is None:
        try:
            text = Path("/proc/self/mountinfo").read_text()
        except OSError:
            text = ""
    return [item for item in DENIED_HOST_PATHS if item in text]


def filesystem_rules() -> list[dict[str, str]]:
    return [
        {"target": "plugin_environment", "access": "read_execute", "mode": "ro"},
        {"target": "host_runtime", "access": "read_execute", "mode": "ro"},
        {"target": "plugin_temp", "access": "read_write", "mode": "rw,noexec,nosuid,nodev"},
        {"target": "call_scoped_transfers", "access": "read_write", "mode": "rw,noexec,nosuid,nodev"},
        {"target": "home,repository,content,drafts,credentials", "access": "deny", "mode": "hidden"},
    ]


__all__ = ["DENIED_HOST_PATHS", "filesystem_rules", "mountinfo_contains_forbidden_roots"]
