from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContractError(RuntimeError):
    code: str
    user_message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.user_message)


class RuntimeValidationError(RuntimeContractError):
    pass


class CapabilityResolutionError(RuntimeContractError):
    pass
