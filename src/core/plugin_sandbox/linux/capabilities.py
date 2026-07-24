"""Linux capability inspection."""

from __future__ import annotations

from pathlib import Path


def current_capability_summary() -> dict[str, str]:
    summary: dict[str, str] = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("CapEff:", "CapPrm:", "CapInh:", "CapAmb:")):
                key, value = line.split(":", maxsplit=1)
                summary[key] = value.strip()
    except OSError:
        summary["error"] = "unavailable"
    return summary


def ambient_empty(summary: dict[str, str]) -> bool:
    return summary.get("CapAmb", "0").strip("0") == ""


__all__ = ["ambient_empty", "current_capability_summary"]
