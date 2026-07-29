"""Recovery helpers for the local encrypted secret backend."""

from __future__ import annotations

from pathlib import Path


def scan_orphans(vault_dir: Path) -> dict[str, object]:
    temps = sorted(path.name for path in vault_dir.glob(".*.tmp") if not path.is_symlink())
    return {"orphan_temporary_records": temps, "automatic_plaintext_recovery": False}


__all__ = ["scan_orphans"]
