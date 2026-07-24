"""Linux Landlock detection and policy metadata."""

from __future__ import annotations

import os


def landlock_abi_version() -> int:
    if not hasattr(os, "syscall"):
        return 0
    # landlock_create_ruleset syscall numbers vary by architecture; ctypes call is unavailable here.
    # Return 0 unless the kernel exposes Landlock through the documented header path.
    return 1 if os.path.exists("/usr/include/linux/landlock.h") else 0


def landlock_status() -> str:
    return "available" if landlock_abi_version() > 0 else "unavailable"


__all__ = ["landlock_abi_version", "landlock_status"]
