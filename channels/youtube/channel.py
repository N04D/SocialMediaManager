from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .auth import MINIMAL_SCOPES, OAuthStateStore, build_authorization_url, plan_hash, validate_redirect_uri
from .errors import YouTubeChannelError
from .models import YouTubePublicationEvidence, YouTubePublishPlan
from .transport import YouTubeTransport

SHORT_MAX_SECONDS = 180
SHORT_CAPABILITIES = (
    "channel.publish.video",
    "channel.publish.short_video",
    "publication.video",
    "publication.status.read",
)


def asset_checksum(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_short_asset(plan: YouTubePublishPlan, *, require_short: bool = True) -> dict[str, Any]:
    path = Path(plan.asset_path)
    if not path.is_file() or not path.stat().st_size:
        raise YouTubeChannelError("youtube.invalid_media", "The managed video asset is missing or empty.")
    if plan.mime_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise YouTubeChannelError("youtube.invalid_media", "The asset is not a supported video file.")
    observed = asset_checksum(path)
    if plan.asset_checksum and observed != plan.asset_checksum:
        raise YouTubeChannelError("youtube.asset_changed", "The confirmed video asset changed.")
    if plan.title.strip() == "":
        raise YouTubeChannelError("youtube.invalid_metadata", "A YouTube title is required.")
    if plan.privacy not in {"private", "unlisted", "public"}:
        raise YouTubeChannelError("youtube.invalid_metadata", "Privacy must be private, unlisted, or public.")
    if not isinstance(plan.description, str):
        raise YouTubeChannelError("youtube.invalid_metadata", "Description must be text.")
    if plan.duration <= 0:
        raise YouTubeChannelError("youtube.invalid_media", "Video duration could not be verified.")
    if require_short and plan.duration > SHORT_MAX_SECONDS:
        raise YouTubeChannelError("youtube.short_too_long", "This video is longer than the 180 second Short limit.")
    if require_short and plan.width and plan.height and plan.width > plan.height:
        raise YouTubeChannelError(
            "youtube.short_orientation", "This video is landscape and may not be classified as a Short."
        )
    return {
        "file_exists": True,
        "checksum": observed,
        "duration": plan.duration,
        "width": plan.width,
        "height": plan.height,
        "short_eligible": not plan.width or plan.width <= plan.height,
    }


def confirmation_checksum(plan: YouTubePublishPlan) -> str:
    return plan_hash(
        {
            "execution_id": plan.execution_id,
            "asset_id": plan.asset_id,
            "asset_checksum": plan.asset_checksum,
            "title": plan.title,
            "description": plan.description,
            "privacy": plan.privacy,
            "notify_subscribers": plan.notify_subscribers,
            "channel_account_id": plan.channel_account_id,
            "channel_id": plan.channel_id,
            "variant_id": plan.variant_id,
            "revision_id": plan.revision_id,
        }
    )


class YouTubeChannelService:
    service_name = "channel_runtime"

    def __init__(
        self,
        *,
        config: Any = None,
        transport: YouTubeTransport | None = None,
        state_store: OAuthStateStore | None = None,
        session_store_path: str | Path | None = None,
        secret_reader: Any | None = None,
    ):
        self.config = config
        self.transport = transport
        self.state_store = state_store or OAuthStateStore()
        self.session_store_path = Path(session_store_path) if session_store_path else None
        self.secret_reader = secret_reader
        self.sessions: dict[str, dict[str, Any]] = self._load_sessions()
        self.publications: dict[str, YouTubePublicationEvidence] = {}
        self._channel_identity: dict[str, str] = {}

    def _load_sessions(self) -> dict[str, dict[str, Any]]:
        if self.session_store_path is None or not self.session_store_path.is_file():
            return {}
        try:
            payload = json.loads(self.session_store_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_sessions(self) -> None:
        if self.session_store_path is None:
            return
        self.session_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_store_path.write_text(json.dumps(self.sessions, sort_keys=True), encoding="utf-8")

    def health_check(self, *, channel_account_id: str = "") -> dict[str, Any]:
        configured = (
            bool(getattr(self.config, "youtube_client_id", "") and getattr(self.config, "youtube_redirect_uri", ""))
            if self.config
            else False
        )
        return {
            "status": "ready",
            "plugin_registered": True,
            "transport_available": self.transport is not None,
            "configured": configured,
            "connection_status": self.connection_status(channel_account_id).get("status", "not_configured"),
            "default_privacy": str(getattr(self.config, "youtube_default_privacy", "private")),
            "notify_subscribers": bool(getattr(self.config, "youtube_notify_subscribers", False)),
            "scopes": list(MINIMAL_SCOPES),
        }

    def connection_status(self, channel_account_id: str = "") -> dict[str, Any]:
        return {
            "channel_account_id": channel_account_id,
            "status": "connected" if channel_account_id in self._channel_identity else "not_configured",
            "channel_id": self._channel_identity.get(channel_account_id, ""),
            "channel_name": "",
        }

    def start_connect(self, *, workspace_id: str, channel_account_id: str, redirect_uri: str) -> dict[str, str]:
        redirect_uri = validate_redirect_uri(redirect_uri)
        flow = self.state_store.issue(
            workspace_id=workspace_id, channel_account_id=channel_account_id, redirect_uri=redirect_uri
        )
        client_id = str(getattr(self.config, "youtube_client_id", "") or "")
        if not client_id:
            raise YouTubeChannelError("youtube.oauth.client_missing", "YouTube OAuth client is not configured.")
        return {
            "authorization_url": build_authorization_url(client_id=client_id, redirect_uri=redirect_uri, flow=flow),
            "state": flow.state,
            "scopes": " ".join(flow.scopes),
        }

    def complete_connect(
        self, *, code: str, state: str, workspace_id: str, channel_account_id: str, redirect_uri: str
    ) -> dict[str, Any]:
        flow = self.state_store.consume(
            state,
            workspace_id=workspace_id,
            channel_account_id=channel_account_id,
            redirect_uri=validate_redirect_uri(redirect_uri),
        )
        if self.transport is None:
            raise YouTubeChannelError("youtube.oauth.transport_missing", "YouTube OAuth transport is not configured.")
        client_secret_ref = str(getattr(self.config, "youtube_client_secret_ref", "") or "")
        client_secret = (
            self.secret_reader(client_secret_ref) if callable(self.secret_reader) and client_secret_ref else ""
        )
        if not client_secret:
            raise YouTubeChannelError(
                "youtube.oauth.secret_unavailable", "YouTube OAuth client secret is not available from managed secrets."
            )
        response = self.transport.exchange_code(
            code=code,
            client_id=str(getattr(self.config, "youtube_client_id", "")),
            client_secret=client_secret,
            redirect_uri=flow.redirect_uri,
        )
        token = response.payload.get("access_token")
        if not token:
            raise YouTubeChannelError("youtube.oauth.exchange_failed", "YouTube authorization could not be completed.")
        channel = self.transport.get_channel(access_token=str(token)).payload
        item = (channel.get("items") or [{}])[0]
        self._channel_identity[channel_account_id] = str(item.get("id") or "")
        return {
            "status": "connected",
            "channel_id": self._channel_identity[channel_account_id],
            "channel_name": str((item.get("snippet") or {}).get("title") or ""),
            "scopes": list(flow.scopes),
        }

    def refresh_access_token(self, *, refresh_token: str, client_id: str, client_secret: str) -> str:
        if self.transport is None:
            raise YouTubeChannelError("youtube.oauth.transport_missing", "YouTube OAuth transport is not configured.")
        response = self.transport.refresh_access_token(
            refresh_token=refresh_token, client_id=client_id, client_secret=client_secret
        )
        token = str(response.payload.get("access_token") or "")
        if not token:
            raise YouTubeChannelError(
                "youtube.oauth.reauthorization_required", "YouTube authorization must be renewed."
            )
        return token

    def read_video_metadata(self, *, video_id: str, access_token: str = "") -> dict[str, Any]:
        if self.transport is None:
            raise YouTubeChannelError("youtube.transport_missing", "YouTube transport is not configured.")
        response = self.transport.get_video(video_id=video_id, access_token=access_token)
        items = response.payload.get("items")
        if not isinstance(items, list):
            raise YouTubeChannelError("youtube.response_malformed", "YouTube video metadata response was malformed.")
        if not items:
            raise YouTubeChannelError("youtube.video_not_found", "YouTube video was not found.")
        item = items[0]
        if not isinstance(item, dict):
            raise YouTubeChannelError("youtube.response_malformed", "YouTube video metadata response was malformed.")
        snippet = item.get("snippet") or {}
        status = item.get("status") or {}
        processing = item.get("processingDetails") or {}
        return {
            "video_id": str(item.get("id") or video_id),
            "title": str(snippet.get("title") or ""),
            "description": str(snippet.get("description") or ""),
            "published_at": str(snippet.get("publishedAt") or ""),
            "channel_id": str(snippet.get("channelId") or ""),
            "channel_title": str(snippet.get("channelTitle") or ""),
            "privacy_status": str(status.get("privacyStatus") or ""),
            "processing_status": str(processing.get("processingStatus") or ""),
            "source": "youtube-upload-channel",
        }

    def prepare(self, plan: YouTubePublishPlan) -> dict[str, Any]:
        validation = validate_short_asset(plan)
        return {
            "confirmation_checksum": confirmation_checksum(plan),
            "plan": asdict(plan),
            "validation": validation,
            "privacy": plan.privacy,
            "notify_subscribers": plan.notify_subscribers,
        }

    def publish(
        self, plan: YouTubePublishPlan, *, confirmation: str = "", access_token: str = ""
    ) -> YouTubePublicationEvidence:
        expected = confirmation_checksum(plan)
        if not confirmation or not hmac_compare(confirmation, expected):
            raise YouTubeChannelError(
                "youtube.confirmation_required", "Publishing requires confirmation of the exact video and metadata."
            )
        validate_short_asset(plan)
        existing = self.publications.get(plan.execution_id)
        if existing and existing.remote_video_id:
            return existing
        if self.transport is None:
            raise YouTubeChannelError("youtube.transport_missing", "YouTube transport is not configured.")
        state = self.sessions.setdefault(
            plan.execution_id,
            {"session_url": "", "offset": 0, "total": Path(plan.asset_path).stat().st_size, "created_at": ""},
        )
        if not state["session_url"]:
            response = self.transport.create_upload_session(
                access_token=access_token,
                total_bytes=state["total"],
                metadata={
                    "snippet": {"title": plan.title, "description": plan.description},
                    "status": {"privacyStatus": plan.privacy, "notifySubscribers": plan.notify_subscribers},
                },
            )
            state["session_url"] = str(response.headers.get("Location") or "")
            if not state["session_url"]:
                raise YouTubeChannelError("youtube.upload_session_failed", "YouTube did not create an upload session.")
            self._save_sessions()
        evidence = YouTubePublicationEvidence(
            plan.execution_id,
            plan.asset_id,
            plan.asset_checksum,
            plan.channel_account_id,
            requested_privacy=plan.privacy,
            status="running",
            session_created=True,
            confirmed_plan_checksum=expected,
            variant_id=plan.variant_id,
            revision_id=plan.revision_id,
        )
        self.publications[plan.execution_id] = evidence
        try:
            with Path(plan.asset_path).open("rb") as handle:
                handle.seek(int(state["offset"]))
                while state["offset"] < state["total"]:
                    chunk = handle.read(min(256 * 1024, state["total"] - state["offset"]))
                    response = self.transport.upload_chunk(
                        session_url=state["session_url"],
                        data=chunk,
                        start=state["offset"],
                        total_bytes=state["total"],
                        access_token=access_token,
                    )
                    if response.status == 308:
                        state["offset"] = _next_offset(response, state["offset"] + len(chunk))
                        evidence.bytes_confirmed = state["offset"]
                        self._save_sessions()
                        continue
                    if response.status not in {200, 201} or not response.payload.get("id"):
                        raise YouTubeChannelError("youtube.upload_failed", "YouTube did not return a video ID.")
                    evidence.remote_video_id = str(response.payload["id"])
                    state["offset"] = state["total"]
                    self._save_sessions()
                    break
        except ConnectionError:
            status = self.transport.query_upload_session(
                session_url=state["session_url"], total_bytes=state["total"], access_token=access_token
            )
            if status.status in {200, 201} and status.payload.get("id"):
                evidence.remote_video_id = str(status.payload["id"])
                state["offset"] = state["total"]
            else:
                state["offset"] = _next_offset(status, state["offset"])
                self._save_sessions()
                evidence.status = "uncertain" if state["offset"] >= state["total"] else "interrupted"
                evidence.error_code = "youtube.upload_uncertain"
                evidence.error_message = "Upload connection was interrupted; the same resumable session is retained."
                return evidence
        if not evidence.remote_video_id:
            evidence.status = "uncertain"
            return evidence
        reconciled = self.reconcile(evidence, access_token=access_token)
        return reconciled

    def reconcile(self, evidence: YouTubePublicationEvidence, *, access_token: str = "") -> YouTubePublicationEvidence:
        if not evidence.remote_video_id or self.transport is None:
            return evidence
        response = self.transport.get_video(video_id=evidence.remote_video_id, access_token=access_token)
        item = (response.payload.get("items") or [{}])[0]
        status = item.get("status") or {}
        processing = (item.get("processingDetails") or {}).get("processingStatus") or "processing"
        evidence.observed_privacy = str(status.get("privacyStatus") or "")
        evidence.processing_status = str(processing)
        evidence.status = (
            "processing"
            if processing not in {"succeeded", "failed"}
            else ("processed" if processing == "succeeded" else "processing_failed")
        )
        evidence.remote_url = f"https://www.youtube.com/watch?v={evidence.remote_video_id}"
        evidence.evidence = {
            "remote_video_id": evidence.remote_video_id,
            "processing_status": evidence.processing_status,
            "observed_privacy": evidence.observed_privacy,
        }
        return evidence


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _next_offset(response, fallback: int) -> int:
    value = str(response.headers.get("Range") or "")
    try:
        return int(value.rsplit("-", 1)[1]) + 1 if "-" in value else fallback
    except (ValueError, IndexError):
        return fallback
