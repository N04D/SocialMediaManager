"""Windows AppContainer policy metadata."""

from __future__ import annotations


def appcontainer_available() -> bool:
    return False


def default_capabilities() -> list[str]:
    return []


__all__ = ["appcontainer_available", "default_capabilities"]
