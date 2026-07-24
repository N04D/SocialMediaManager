"""macOS App Sandbox detection."""

from __future__ import annotations


def app_sandbox_entitlement_active() -> bool:
    return False


__all__ = ["app_sandbox_entitlement_active"]
