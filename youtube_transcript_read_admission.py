from __future__ import annotations

from dataclasses import dataclass

from channels.youtube.auth import YOUTUBE_READONLY_SCOPE, YOUTUBE_UPLOAD_SCOPE
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import Install
from youtube_transcript_read_handler import (
    YOUTUBE_OFFICIAL_CAPTIONS_COMPONENT_ID,
    YOUTUBE_TRANSCRIPT_READ_CAPABILITY,
    YouTubeTranscriptReadHandler,
)


@dataclass(frozen=True)
class YouTubeTranscriptReadCandidate:
    component_id: str = YOUTUBE_OFFICIAL_CAPTIONS_COMPONENT_ID
    capability_id: str = YOUTUBE_TRANSCRIPT_READ_CAPABILITY
    read_only: bool = True
    official_api_transport: bool = True
    deterministic_track_selection: bool = True
    bounded_response: bool = True
    required_egress: tuple[str, ...] = ("www.googleapis.com:443",)
    required_secrets: tuple[str, ...] = ("youtube-access-token-ref",)
    required_oauth_scopes: tuple[str, ...] = (YOUTUBE_READONLY_SCOPE, YOUTUBE_UPLOAD_SCOPE)


def evaluate_youtube_transcript_read_admission(
    candidate: YouTubeTranscriptReadCandidate,
    *,
    install: Install | None = None,
    configured_scopes: tuple[str, ...] = (),
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not candidate.read_only:
        reasons.append("BLOCKED_READ_CAPABILITY_MUST_BE_READ_ONLY")
    if not candidate.official_api_transport:
        reasons.append("BLOCKED_UNOFFICIAL_TRANSPORT")
    if not candidate.deterministic_track_selection:
        reasons.append("BLOCKED_TRACK_SELECTION_NONDETERMINISTIC")
    if not candidate.bounded_response:
        reasons.append("BLOCKED_UNBOUNDED_RESPONSE")
    if candidate.component_id != YOUTUBE_OFFICIAL_CAPTIONS_COMPONENT_ID:
        reasons.append(f"BLOCKED_UNEXPECTED_COMPONENT_ID:{candidate.component_id}")
    if candidate.capability_id != YOUTUBE_TRANSCRIPT_READ_CAPABILITY:
        reasons.append(f"BLOCKED_UNEXPECTED_CAPABILITY_ID:{candidate.capability_id}")

    if configured_scopes and not any(scope in configured_scopes for scope in candidate.required_oauth_scopes):
        reasons.append("BLOCKED_AUTH_INSUFFICIENT_SCOPE")
    if not configured_scopes:
        reasons.append("OFFICIAL_TRANSCRIPT_SOURCE_NOT_CONFIGURED")

    if install is not None:
        granted_secrets = set(install.secret_refs or ())
        for ref in candidate.required_secrets:
            if ref not in granted_secrets:
                reasons.append(f"BLOCKED_MISSING_SECRET_REF:{ref}")
        grants = getattr(install, "grants", None)
        allowed = set(getattr(grants, "allowed_capabilities", ()) or ()) if grants else set()
        if candidate.capability_id not in allowed:
            reasons.append("OFFICIAL_TRANSCRIPT_SOURCE_NOT_ACTIVATED")

    return not reasons, reasons


def admit_and_register_youtube_transcript_read_capability(
    registry: CapabilityHandlerRegistry,
    handler: YouTubeTranscriptReadHandler,
    *,
    install: Install | None = None,
    configured_scopes: tuple[str, ...] = (),
) -> tuple[bool, list[str]]:
    candidate = YouTubeTranscriptReadCandidate()
    ok, reasons = evaluate_youtube_transcript_read_admission(
        candidate, install=install, configured_scopes=configured_scopes
    )
    if ok:
        registry.register(handler)
    return ok, reasons
