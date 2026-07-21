"""Fixture and doctor conventions for Plugin SDK v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PluginFixtureScenario:
    """Deterministic fixture scenario metadata."""

    name: str
    description: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    mutates_remote: bool = False


@dataclass(frozen=True)
class PluginDoctorCheck:
    """Read-only doctor check result."""

    status: str
    code: str
    safe_message: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PluginDoctor(Protocol):
    """Read-only plugin doctor interface."""

    def run(self) -> list[PluginDoctorCheck]:
        """Run PASS/WARN/FAIL checks without mutation."""


__all__ = ["PluginDoctor", "PluginDoctorCheck", "PluginFixtureScenario"]
