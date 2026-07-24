"""Policies for external plugin host processes."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SAFE_ENV_ALLOWLIST = {
    "LANG",
    "LC_ALL",
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TZ",
}

BLOCKED_ENV_KEYS = {"PYTHONPATH", "PYTHONHOME", "PIP_CONFIG_FILE", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"}
BLOCKED_RUNTIME_MODULES = {"pip", "ensurepip"}


def sanitized_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_ALLOWLIST}
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SMM_PLUGIN_HOST"] = "1"
    for key in BLOCKED_ENV_KEYS:
        env.pop(key, None)
    if extra:
        env.update({key: value for key, value in extra.items() if key not in BLOCKED_ENV_KEYS})
    return env


def host_runtime_pythonpath(repo_root: Path) -> str:
    return str(repo_root)


def default_python() -> str:
    return sys.executable


__all__ = [
    "BLOCKED_ENV_KEYS",
    "BLOCKED_RUNTIME_MODULES",
    "SAFE_ENV_ALLOWLIST",
    "default_python",
    "sanitized_environment",
]
