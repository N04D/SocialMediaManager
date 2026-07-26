"""Host-owned Linux sandbox launcher.

This module is executed before `plugin_host_runtime`. It sets up namespaces and
mount basics, forks into the PID namespace, and then execs the existing
host-owned runtime. It must never import external plugin code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .native import (
    LINUX_LAUNCHER_CONTRACT_VERSION,
    LINUX_LAUNCHER_VERSION,
    SandboxNativeError,
    drop_ambient_capabilities,
    make_mounts_private,
    mount_minimal_dev,
    mount_proc,
    set_no_new_privs,
)

ISOLATION_NAMESPACE_FLAGS = os.CLONE_NEWNS | os.CLONE_NEWPID | os.CLONE_NEWIPC | os.CLONE_NEWUTS | os.CLONE_NEWNET


def _write(path: str, value: str) -> None:
    Path(path).write_text(value, encoding="utf-8")


def _map_current_user(host_uid: int, host_gid: int) -> None:
    try:
        _write("/proc/self/setgroups", "deny\n")
    except OSError:
        pass
    _write("/proc/self/uid_map", f"0 {host_uid} 1\n")
    _write("/proc/self/gid_map", f"0 {host_gid} 1\n")
    os.setgid(0)
    os.setuid(0)


def _setup_namespaces() -> dict[str, object]:
    host_uid = os.getuid()
    host_gid = os.getgid()
    os.unshare(os.CLONE_NEWUSER)
    _map_current_user(host_uid, host_gid)
    os.unshare(ISOLATION_NAMESPACE_FLAGS)
    make_mounts_private()
    try:
        os.sethostname(b"smm-plugin")
    except OSError:
        pass
    return {"namespaces": "created"}


def _child_exec(command: list[str], env: dict[str, str]) -> None:
    mount_proc()
    mount_minimal_dev()
    set_no_new_privs()
    drop_ambient_capabilities()
    os.execve(command[0], command, env)


def run(command: list[str], env: dict[str, str]) -> int:
    setup: dict[str, object] = {
        "launcher_version": LINUX_LAUNCHER_VERSION,
        "launcher_contract_version": LINUX_LAUNCHER_CONTRACT_VERSION,
    }
    try:
        setup.update(_setup_namespaces())
    except Exception as exc:
        print(json.dumps({"sandbox_launcher_error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 126
    pid = os.fork()
    if pid == 0:
        try:
            _child_exec(command, env)
        except Exception as exc:  # pragma: no cover - child failure path.
            print(json.dumps({"sandbox_child_error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
            os._exit(127)
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    raise SandboxNativeError("sandboxed child exited unexpectedly")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linux-plugin-sandbox-launcher")
    parser.add_argument("--env-json", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command or any(part in {"sh", "bash", "-c", "eval"} for part in command):
        print(json.dumps({"sandbox_launcher_error": "invalid_command"}), file=sys.stderr)
        return 125
    env = json.loads(Path(args.env_json).read_text())
    return run(command, {str(k): str(v) for k, v in env.items()})


if __name__ == "__main__":
    raise SystemExit(main())
