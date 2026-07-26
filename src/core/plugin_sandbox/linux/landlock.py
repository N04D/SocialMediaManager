"""Linux Landlock detection and policy metadata."""

from __future__ import annotations

from .native import landlock_abi


def landlock_abi_version() -> int:
    return landlock_abi()


def landlock_status() -> str:
    return "available" if landlock_abi_version() > 0 else "unavailable"


__all__ = ["landlock_abi_version", "landlock_status"]
