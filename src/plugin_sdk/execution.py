"""Execution reporting facade for channel plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ExecutionReport:
    kind: str
    value: str
    at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionReporter(Protocol):
    """Monotone reporting surface; plugins never import execution repositories."""

    async def report_phase(self, phase: str, metadata: dict[str, Any] | None = None) -> None: ...
    async def report_mutation_state(self, state: str, metadata: dict[str, Any] | None = None) -> None: ...
    async def report_remote_acknowledged(self, remote_id: str, metadata: dict[str, Any] | None = None) -> None: ...
    async def report_verification(self, state: str, metadata: dict[str, Any] | None = None) -> None: ...
    async def report_cleanup(self, state: str, metadata: dict[str, Any] | None = None) -> None: ...


__all__ = ["ExecutionReport", "ExecutionReporter"]
