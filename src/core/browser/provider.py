from __future__ import annotations

from typing import Any, Protocol

from .models import BrowserProfileStatus, BrowserSessionOptions, HumanTakeoverRequest
from .session import BrowserSession


class BrowserProvider(Protocol):
    def create_session(self, options: BrowserSessionOptions) -> BrowserSession: ...

    def close_session(self, session_id: str) -> None: ...

    def get_session(self, session_id: str) -> BrowserSession | None: ...

    def profile_status(self, profile_id: str) -> BrowserProfileStatus: ...

    def health_check(self) -> dict[str, Any]: ...

    def request_human_takeover(self, request: HumanTakeoverRequest) -> dict[str, Any]: ...
