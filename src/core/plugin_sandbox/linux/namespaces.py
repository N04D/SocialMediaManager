"""Linux namespace inspection."""

from __future__ import annotations

from pathlib import Path

NAMESPACE_NAMES = ["user", "mnt", "pid", "ipc", "uts", "net"]


def namespace_ids(pid: str = "self") -> dict[str, str]:
    result: dict[str, str] = {}
    for name in NAMESPACE_NAMES:
        path = Path("/proc") / pid / "ns" / name
        try:
            result[name] = str(path.readlink())
        except OSError:
            result[name] = "unavailable"
    return result


def namespace_support() -> dict[str, bool]:
    return {name: (Path("/proc/self/ns") / name).exists() for name in NAMESPACE_NAMES}


__all__ = ["NAMESPACE_NAMES", "namespace_ids", "namespace_support"]
