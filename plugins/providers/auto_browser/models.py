from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AutoBrowserElement:
    element_id: str
    role: str = ""
    name: str = ""
    text: str = ""
    label: str = ""
    test_id: str = ""
    placeholder: str = ""
    title: str = ""
    alt_text: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    enabled: bool = True


@dataclass
class AutoBrowserSessionMapping:
    local_session_id: str
    remote_session_id: str
    provider_id: str
    profile_id: str
    auth_profile_name: str
    purpose: str = ""
    job_id: str = ""
    status: str = "active"
    takeover_status: str = "not_required"
    created_at: str = ""
    updated_at: str = ""
    last_remote_status: str = ""
    artifact_references: list[dict[str, Any]] = field(default_factory=list)
    application_id: str = "social-media-manager"
    workspace_hash: str = ""
    channel_account_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutoBrowserReconciliationItem:
    kind: str
    local_session_id: str = ""
    remote_session_id: str = ""
    profile_id: str = ""
    status: str = ""
    safe_to_cleanup: bool = False
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
