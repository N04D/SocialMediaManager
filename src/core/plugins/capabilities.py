from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Capability:
    id: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Capability id is required.")
