"""Resource containment helpers for plugin hosts."""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from dataclasses import asdict

from .models import PluginHostResourcePolicy


class PluginHostResourceController:
    def __init__(self, policy: PluginHostResourcePolicy | None = None) -> None:
        self.policy = policy or PluginHostResourcePolicy()

    def containment_status(self) -> str:
        if sys.platform == "win32":
            return "degraded_resource_containment"
        try:
            import resource  # noqa: PLC0415
        except ImportError:
            return "degraded_resource_containment"
        required = ["RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_NOFILE", "RLIMIT_CORE", "RLIMIT_FSIZE"]
        return "enforced" if all(hasattr(resource, name) for name in required) else "degraded_resource_containment"

    def preexec_fn(self) -> Callable[[], None] | None:
        if sys.platform == "win32":
            return None

        def apply_limits() -> None:
            os.setsid()
            import resource  # noqa: PLC0415

            limits = [
                ("RLIMIT_AS", self.policy.memory_bytes),
                ("RLIMIT_CPU", self.policy.cpu_seconds),
                ("RLIMIT_NOFILE", self.policy.open_files),
                ("RLIMIT_CORE", self.policy.core_dump_bytes),
                ("RLIMIT_FSIZE", self.policy.created_file_bytes),
            ]
            for name, value in limits:
                if hasattr(resource, name):
                    resource.setrlimit(getattr(resource, name), (value, value))

        return apply_limits

    def creationflags(self) -> int:
        return getattr(subprocess_constants(), "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0

    def terminate_group(self, pid: int) -> None:
        if sys.platform == "win32":
            try:
                os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            except Exception:
                os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pid, signal.SIGTERM)

    def kill_group(self, pid: int) -> None:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pid, signal.SIGKILL)

    def to_public(self) -> dict[str, object]:
        payload = asdict(self.policy)
        payload["containment_status"] = self.containment_status()
        return payload


def subprocess_constants() -> object:
    import subprocess  # noqa: PLC0415

    return subprocess


__all__ = ["PluginHostResourceController"]
