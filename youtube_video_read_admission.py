from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import Install
from youtube_video_read_handler import YOUTUBE_UPLOADS_COMPONENT_ID, YOUTUBE_VIDEO_READ_CAPABILITY, YouTubeVideoReadHandler


@dataclass(frozen=True)
class YouTubeReadCapabilityCandidate:
    component_id: str = YOUTUBE_UPLOADS_COMPONENT_ID
    capability_id: str = YOUTUBE_VIDEO_READ_CAPABILITY
    read_only: bool = True
    required_egress: tuple[str, ...] = ("www.googleapis.com:443",)
    required_secrets: tuple[str, ...] = ("youtube-access-token-ref",)


def evaluate_youtube_read_capability_admission(
    candidate: YouTubeReadCapabilityCandidate,
    *,
    install: Install | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not candidate.read_only:
        reasons.append("BLOCKED_READ_CAPABILITY_MUST_BE_READ_ONLY")

    if candidate.component_id != YOUTUBE_UPLOADS_COMPONENT_ID:
        reasons.append(f"BLOCKED_UNEXPECTED_COMPONENT_ID:{candidate.component_id}")

    if candidate.capability_id != YOUTUBE_VIDEO_READ_CAPABILITY:
        reasons.append(f"BLOCKED_UNEXPECTED_CAPABILITY_ID:{candidate.capability_id}")

    if install is not None:
        granted_destinations = set()
        if hasattr(install, "grants") and hasattr(install.grants, "permission_grants"):
            network = getattr(install.grants.permission_grants, "network", None)
            egress_list = getattr(network, "egress", ()) if network else ()
            for rule in egress_list:
                if hasattr(rule, "host") and hasattr(rule, "port"):
                    granted_destinations.add(f"{rule.host}:{rule.port}")
                elif isinstance(rule, str):
                    granted_destinations.add(rule)

        for req in candidate.required_egress:
            if req not in granted_destinations:
                reasons.append(f"BLOCKED_REQUIRED_EGRESS_DENIED:{req}")

        granted_secrets = set()
        if hasattr(install, "secret_refs"):
            if isinstance(install.secret_refs, (list, tuple, set)):
                granted_secrets = set(install.secret_refs)
            elif isinstance(install.secret_refs, dict):
                granted_secrets = set(install.secret_refs.keys())
        for req_sec in candidate.required_secrets:
            if req_sec not in granted_secrets:
                reasons.append(f"BLOCKED_MISSING_SECRET_REF:{req_sec}")

    return len(reasons) == 0, reasons


def admit_and_register_youtube_read_capability(
    registry: CapabilityHandlerRegistry,
    handler: YouTubeVideoReadHandler,
    *,
    install: Install | None = None,
) -> tuple[bool, list[str]]:
    candidate = YouTubeReadCapabilityCandidate()
    ok, reasons = evaluate_youtube_read_capability_admission(candidate, install=install)
    if ok:
        registry.register(handler)
    return ok, reasons
