"""Child-side Linux sandbox attestation and enforcement."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.core.plugin_sandbox.linux.capabilities import ambient_empty, current_capability_summary
from src.core.plugin_sandbox.linux.landlock import landlock_abi_version
from src.core.plugin_sandbox.linux.namespaces import namespace_ids
from src.core.plugin_sandbox.linux.native import (
    SandboxNativeError,
    apply_landlock,
    apply_seccomp_denylist,
    drop_ambient_capabilities,
    no_new_privs_status,
    set_no_new_privs,
)
from src.core.plugin_sandbox.linux.seccomp import profile_checksum, seccomp_status


def _read_routes() -> list[str]:
    path = Path("/proc/net/route")
    try:
        return path.read_text().splitlines()[1:]
    except OSError:
        return []


def _network_denied() -> bool:
    try:
        with socket.create_connection(("198.51.100.1", 9), timeout=0.2):
            return False
    except OSError:
        return True


def _thread_works() -> bool:
    flag = {"ok": False}

    def worker() -> None:
        flag["ok"] = True

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)
    return flag["ok"]


def _denial_probes() -> dict[str, bool]:
    probes: dict[str, bool] = {}
    for name, path in {
        "repository_read_denied": Path(os.environ.get("SMM_PLUGIN_HOST_REPO", "/nonexistent")),
        "content_read_denied": Path(os.environ.get("SMM_PLUGIN_HOST_REPO", "/nonexistent")) / "content",
        "drafts_read_denied": Path(os.environ.get("SMM_PLUGIN_HOST_REPO", "/nonexistent")) / "drafts",
        "home_read_denied": Path.home(),
    }.items():
        try:
            target = path if path.is_file() else path / "."
            os.listdir(target)
            probes[name] = False
        except OSError:
            probes[name] = True
    try:
        Path(sys.executable).write_text("x", encoding="utf-8")
        probes["code_write_denied"] = False
    except OSError:
        probes["code_write_denied"] = True
    try:
        temp = Path(tempfile.gettempdir()) / "smm-sandbox-write-probe"
        temp.write_text("ok", encoding="utf-8")
        temp.unlink(missing_ok=True)
        probes["temp_write_allowed"] = True
    except OSError:
        probes["temp_write_allowed"] = False
    probes["direct_network_denied"] = _network_denied()
    probes["thread_allowed"] = _thread_works()
    return probes


def _runtime_paths() -> list[Path]:
    paths = {Path(sys.executable).resolve().parents[1], Path(tempfile.gettempdir()).resolve()}
    for item in sys.path:
        if item:
            try:
                paths.add(Path(item).resolve())
            except OSError:
                pass
    install_root = os.environ.get("SMM_PLUGIN_INSTALL_ROOT")
    plugin_id = os.environ.get("SMM_PLUGIN_ID")
    plugin_version = os.environ.get("SMM_PLUGIN_VERSION")
    if install_root and plugin_id and plugin_version:
        paths.add((Path(install_root) / plugin_id / "installs" / plugin_version).resolve())
    return sorted(paths)


def enforce_and_attest() -> dict[str, Any]:
    if os.environ.get("SMM_PLUGIN_SANDBOX_STATUS") == "development_override":
        caps = current_capability_summary()
        return {
            "status": "development_override",
            "namespace_ids": namespace_ids(),
            "no_new_privs": no_new_privs_status(),
            "capabilities": caps,
            "ambient_capabilities_empty": ambient_empty(caps),
            "seccomp_mode": seccomp_status(),
            "landlock": {"landlock_supported": False, "landlock_abi": landlock_abi_version()},
            "denial_probes": {},
            "errors": ["development_override"],
        }
    errors: list[str] = []
    landlock: dict[str, Any] = {"landlock_supported": False, "landlock_abi": landlock_abi_version()}
    seccomp: dict[str, Any] = {}
    try:
        set_no_new_privs()
        drop_ambient_capabilities()
    except OSError as exc:
        errors.append(f"privilege_setup:{exc.errno}")
    try:
        readonly = _runtime_paths()
        readwrite = [Path(tempfile.gettempdir()).resolve()]
        landlock = apply_landlock(readonly_paths=readonly, readwrite_paths=readwrite)
    except (OSError, SandboxNativeError) as exc:
        errors.append(f"landlock:{type(exc).__name__}")
    try:
        seccomp = apply_seccomp_denylist()
    except (OSError, SandboxNativeError) as exc:
        errors.append(f"seccomp:{type(exc).__name__}")
    caps = current_capability_summary()
    evidence = {
        "namespace_ids": namespace_ids(),
        "no_new_privs": no_new_privs_status(),
        "capabilities": caps,
        "ambient_capabilities_empty": ambient_empty(caps),
        "seccomp_mode": seccomp_status(),
        "seccomp_profile_checksum": profile_checksum(os.environ.get("SMM_PLUGIN_SANDBOX_SECCOMP_PROFILE", "")),
        "seccomp": seccomp,
        "landlock": landlock,
        "network_routes": _read_routes(),
        "denial_probes": _denial_probes(),
        "errors": errors,
    }
    evidence["status"] = "enforced" if _evidence_is_enforced(evidence) else "sandbox_verification_failed"
    return evidence


def _evidence_is_enforced(evidence: dict[str, Any]) -> bool:
    probes = evidence.get("denial_probes", {})
    caps = evidence.get("capabilities", {})
    return bool(
        evidence.get("no_new_privs")
        and evidence.get("seccomp_mode") == "2"
        and evidence.get("landlock", {}).get("landlock_supported")
        and evidence.get("ambient_capabilities_empty")
        and caps.get("CapAmb", "0") == "0000000000000000"
        and probes.get("repository_read_denied")
        and probes.get("content_read_denied")
        and probes.get("drafts_read_denied")
        and probes.get("code_write_denied")
        and probes.get("temp_write_allowed")
        and probes.get("direct_network_denied")
        and probes.get("thread_allowed")
        and not evidence.get("errors")
    )


def to_safe_json(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, sort_keys=True)


__all__ = ["enforce_and_attest", "to_safe_json"]
