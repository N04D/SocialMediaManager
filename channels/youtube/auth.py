from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from .errors import YouTubeChannelError

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
MINIMAL_SCOPES = (YOUTUBE_UPLOAD_SCOPE,)


@dataclass(frozen=True)
class OAuthFlow:
    state: str
    workspace_id: str
    channel_account_id: str
    redirect_uri: str
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    consumed: bool = False


class OAuthStateStore:
    def __init__(self, *, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._flows: dict[str, OAuthFlow] = {}

    def issue(
        self, *, workspace_id: str, channel_account_id: str, redirect_uri: str, scopes: tuple[str, ...] = MINIMAL_SCOPES
    ) -> OAuthFlow:
        now = datetime.now(UTC)
        flow = OAuthFlow(
            state=secrets.token_urlsafe(32),
            workspace_id=workspace_id,
            channel_account_id=channel_account_id,
            redirect_uri=redirect_uri,
            scopes=tuple(sorted(set(scopes))),
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        self._flows[flow.state] = flow
        return flow

    def consume(self, state: str, *, workspace_id: str, channel_account_id: str, redirect_uri: str) -> OAuthFlow:
        flow = self._flows.get(state)
        if flow is None or flow.consumed:
            raise YouTubeChannelError("youtube.oauth.state_replay", "OAuth state is missing or already used.")
        if flow.expires_at <= datetime.now(UTC):
            raise YouTubeChannelError("youtube.oauth.state_expired", "OAuth state has expired.")
        if (flow.workspace_id, flow.channel_account_id, flow.redirect_uri) != (
            workspace_id,
            channel_account_id,
            redirect_uri,
        ):
            raise YouTubeChannelError("youtube.oauth.state_mismatch", "OAuth state context did not match.")
        self._flows[state] = OAuthFlow(**{**flow.__dict__, "consumed": True})
        return flow


def validate_redirect_uri(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise YouTubeChannelError("youtube.oauth.redirect_invalid", "The OAuth redirect URI is invalid.")
    return value.rstrip("/")


def build_authorization_url(*, client_id: str, redirect_uri: str, flow: OAuthFlow) -> str:
    validate_redirect_uri(redirect_uri)
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(flow.scopes),
            "state": flow.state,
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def redact_tokens(value):
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(part in key.lower() for part in ("token", "secret", "authorization"))
                else redact_tokens(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_tokens(item) for item in value]
    if isinstance(value, str) and (value.startswith("Bearer ") or "access_token" in value):
        return "[REDACTED]"
    return value


def plan_hash(payload: dict) -> str:
    import json

    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
