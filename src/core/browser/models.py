from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class BrowserSessionStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    ACTIVE = "active"
    DEGRADED = "degraded"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    ERROR = "error"
    HUMAN_TAKEOVER = "human_takeover"


class HumanTakeoverStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUESTED = "requested"
    AVAILABLE = "available"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class BrowserSessionOptions:
    profile_id: str
    headless: bool = True
    exclusive: bool = True
    remote_debugging_url: str = ""
    start_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserProfileStatus:
    profile_id: str
    available: bool
    busy: bool = False
    stale: bool = False
    owner: str = ""
    lock_path: str = ""
    message: str = ""


@dataclass(frozen=True)
class BrowserTarget:
    role: str = ""
    accessible_name: str = ""
    text: str = ""
    label: str = ""
    test_id: str = ""
    placeholder: str = ""
    title: str = ""
    alt_text: str = ""
    stable_attribute: str = ""
    stable_attribute_value: str = ""
    css: str = ""
    xpath: str = ""
    exact: bool = False
    index: int = 0
    timeout_millis: int = 0
    require_visible: bool = False

    def __post_init__(self) -> None:
        if not any(
            [
                self.role,
                self.accessible_name,
                self.text,
                self.label,
                self.test_id,
                self.placeholder,
                self.title,
                self.alt_text,
                self.stable_attribute,
                self.css,
                self.xpath,
            ]
        ):
            raise ValueError("BrowserTarget needs at least one locator strategy.")


@dataclass(frozen=True)
class BrowserSnapshot:
    session_id: str
    url: str
    title: str = ""
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserArtifact:
    id: str
    kind: str
    path: Path | None = None
    content_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HumanTakeoverRequest:
    session_id: str
    reason: str
    timeout_seconds: int = 600
    metadata: dict[str, Any] = field(default_factory=dict)
