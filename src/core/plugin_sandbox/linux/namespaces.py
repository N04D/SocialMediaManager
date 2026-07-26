"""Linux namespace inspection."""

from __future__ import annotations

import subprocess
import sys
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


def namespace_enforcement_probe() -> dict[str, bool | str]:
    code = r"""
import os, sys
host_uid=os.getuid()
host_gid=os.getgid()
try:
    os.unshare(os.CLONE_NEWUSER)
    try:
        with open('/proc/self/setgroups','w') as handle:
            handle.write('deny\n')
    except OSError:
        pass
    with open('/proc/self/uid_map','w') as handle:
        handle.write(f'0 {host_uid} 1\n')
    with open('/proc/self/gid_map','w') as handle:
        handle.write(f'0 {host_gid} 1\n')
    os.setgid(0)
    os.setuid(0)
    os.unshare(os.CLONE_NEWNS|os.CLONE_NEWPID|os.CLONE_NEWIPC|os.CLONE_NEWUTS|os.CLONE_NEWNET)
except Exception as exc:
    print(type(exc).__name__)
    sys.exit(1)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    return {
        "supported": result.returncode == 0,
        "error": result.stdout.strip() or result.stderr.strip(),
    }


__all__ = ["NAMESPACE_NAMES", "namespace_enforcement_probe", "namespace_ids", "namespace_support"]
