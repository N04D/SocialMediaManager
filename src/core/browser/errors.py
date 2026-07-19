from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserProviderError(RuntimeError):
    code: str
    user_message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.user_message)


class BrowserUnavailableError(BrowserProviderError):
    pass


class BrowserSessionError(BrowserProviderError):
    pass


class BrowserNavigationError(BrowserSessionError):
    pass


class BrowserInteractionError(BrowserSessionError):
    pass


class BrowserProfileBusyError(BrowserProviderError):
    pass


class BrowserAuthenticationRequiredError(BrowserProviderError):
    pass


class HumanTakeoverRequiredError(BrowserProviderError):
    pass
