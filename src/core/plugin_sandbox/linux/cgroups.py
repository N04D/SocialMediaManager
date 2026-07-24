"""Linux cgroup v2 helpers."""

from __future__ import annotations

from pathlib import Path


def cgroup_v2_available() -> bool:
    return Path("/sys/fs/cgroup/cgroup.controllers").exists()


def cgroup_summary() -> dict[str, object]:
    return {"available": cgroup_v2_available(), "required": False}


__all__ = ["cgroup_summary", "cgroup_v2_available"]
