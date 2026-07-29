"""Permission helpers for local encrypted secret storage."""

from pathlib import Path


def is_restrictive(path: Path) -> bool:
    return (path.stat().st_mode & 0o077) == 0


__all__ = ["is_restrictive"]
