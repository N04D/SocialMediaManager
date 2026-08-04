from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .auth import redact_tokens
from .errors import YouTubeChannelError

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEO_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


@dataclass
class YouTubeResponse:
    status: int
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


class YouTubeTransport:
    def create_upload_session(
        self, *, access_token: str, metadata: dict[str, Any], total_bytes: int
    ) -> YouTubeResponse:
        raise NotImplementedError

    def upload_chunk(
        self, *, session_url: str, data: bytes, start: int, total_bytes: int, access_token: str
    ) -> YouTubeResponse:
        raise NotImplementedError

    def query_upload_session(self, *, session_url: str, total_bytes: int, access_token: str) -> YouTubeResponse:
        raise NotImplementedError

    def get_video(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        raise NotImplementedError

    def exchange_code(self, *, code: str, client_id: str, client_secret: str, redirect_uri: str) -> YouTubeResponse:
        raise NotImplementedError

    def get_channel(self, *, access_token: str) -> YouTubeResponse:
        raise NotImplementedError

    def refresh_access_token(self, *, refresh_token: str, client_id: str, client_secret: str) -> YouTubeResponse:
        raise NotImplementedError


class HttpYouTubeTransport(YouTubeTransport):
    """Small official-API boundary. No callers issue raw HTTP requests."""

    def __init__(self, *, timeout: float = 30.0):
        self.timeout = timeout

    def _request(
        self,
        url: str,
        *,
        method: str,
        access_token: str = "",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> YouTubeResponse:
        request_headers = {"Accept": "application/json", "User-Agent": "SocialMediaManager YouTube/0.1.0"}
        if access_token:
            request_headers["Authorization"] = f"Bearer {access_token}"
        request_headers.update(headers or {})
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                return YouTubeResponse(
                    response.status, payload if isinstance(payload, dict) else {}, dict(response.headers)
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read(1_000_000)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            raise YouTubeChannelError(
                _http_error_code(exc.code),
                "YouTube API request failed.",
                {"http_status": exc.code, "response": redact_tokens(payload)},
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise YouTubeChannelError("youtube.network_error", "YouTube API request failed.") from exc

    def create_upload_session(
        self, *, access_token: str, metadata: dict[str, Any], total_bytes: int
    ) -> YouTubeResponse:
        query = urllib.parse.urlencode({"part": "snippet,status", "uploadType": "resumable"})
        body = json.dumps({"snippet": metadata["snippet"], "status": metadata["status"]}).encode()
        return self._request(
            f"{UPLOAD_ENDPOINT}?{query}",
            method="POST",
            access_token=access_token,
            body=body,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(total_bytes),
                "X-Upload-Content-Type": "video/mp4",
            },
        )

    def upload_chunk(
        self, *, session_url: str, data: bytes, start: int, total_bytes: int, access_token: str
    ) -> YouTubeResponse:
        return self._request(
            session_url,
            method="PUT",
            access_token=access_token,
            body=data,
            headers={
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{start + len(data) - 1}/{total_bytes}",
                "Content-Type": "video/mp4",
            },
        )

    def query_upload_session(self, *, session_url: str, total_bytes: int, access_token: str) -> YouTubeResponse:
        return self._request(
            session_url,
            method="PUT",
            access_token=access_token,
            body=b"",
            headers={"Content-Length": "0", "Content-Range": f"bytes */{total_bytes}", "Content-Type": "video/mp4"},
        )

    def get_video(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        query = urllib.parse.urlencode({"part": "status,processingDetails,snippet", "id": video_id})
        return self._request(f"{VIDEO_ENDPOINT}?{query}", method="GET", access_token=access_token)

    def exchange_code(self, *, code: str, client_id: str, client_secret: str, redirect_uri: str) -> YouTubeResponse:
        body = urllib.parse.urlencode(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode()
        return self._request(
            TOKEN_ENDPOINT, method="POST", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    def get_channel(self, *, access_token: str) -> YouTubeResponse:
        query = urllib.parse.urlencode({"part": "snippet", "mine": "true"})
        return self._request(
            f"{VIDEO_ENDPOINT.rsplit('/', 1)[0]}/channels?{query}", method="GET", access_token=access_token
        )

    def refresh_access_token(self, *, refresh_token: str, client_id: str, client_secret: str) -> YouTubeResponse:
        body = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode()
        return self._request(
            TOKEN_ENDPOINT, method="POST", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )


class FakeYouTubeTransport(YouTubeTransport):
    def __init__(
        self,
        *,
        video_id: str = "youtube-test-video",
        processing_status: str = "succeeded",
        observed_privacy: str = "private",
        fail_after_bytes: int | None = None,
    ):
        self.video_id = video_id
        self.processing_status = processing_status
        self.observed_privacy = observed_privacy
        self.fail_after_bytes = fail_after_bytes
        self.requests: list[dict[str, Any]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.create_count = 0

    def create_upload_session(
        self, *, access_token: str, metadata: dict[str, Any], total_bytes: int
    ) -> YouTubeResponse:
        self.create_count += 1
        url = f"https://upload.test/session/{self.create_count}"
        self.sessions[url] = {"offset": 0, "total": total_bytes, "metadata": metadata, "complete": False}
        self.requests.append({"method": "POST", "endpoint": "videos.insert", "metadata": redact_tokens(metadata)})
        return YouTubeResponse(200, {}, {"Location": url})

    def upload_chunk(
        self, *, session_url: str, data: bytes, start: int, total_bytes: int, access_token: str
    ) -> YouTubeResponse:
        state = self.sessions[session_url]
        self.requests.append({"method": "PUT", "endpoint": "resumable", "start": start, "bytes": len(data)})
        if self.fail_after_bytes is not None and start < self.fail_after_bytes <= start + len(data):
            raise ConnectionError("simulated connection loss")
        if start != state["offset"]:
            return YouTubeResponse(308, {}, {"Range": f"bytes=0-{state['offset'] - 1}"})
        state["offset"] += len(data)
        if state["offset"] < total_bytes:
            return YouTubeResponse(308, {}, {"Range": f"bytes=0-{state['offset'] - 1}"})
        state["complete"] = True
        return YouTubeResponse(201, {"id": self.video_id}, {})

    def query_upload_session(self, *, session_url: str, total_bytes: int, access_token: str) -> YouTubeResponse:
        state = self.sessions[session_url]
        self.requests.append({"method": "PUT", "endpoint": "resumable-status"})
        if state["complete"]:
            return YouTubeResponse(201, {"id": self.video_id}, {})
        return YouTubeResponse(308, {}, {"Range": f"bytes=0-{state['offset'] - 1}" if state["offset"] else ""})

    def get_video(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        self.requests.append({"method": "GET", "endpoint": "videos.list", "id": video_id})
        return YouTubeResponse(
            200,
            {
                "items": [
                    {
                        "id": video_id,
                        "status": {"privacyStatus": self.observed_privacy},
                        "processingDetails": {"processingStatus": self.processing_status},
                    }
                ]
            },
            {},
        )

    def exchange_code(self, **kwargs) -> YouTubeResponse:
        self.requests.append({"method": "POST", "endpoint": "oauth.token"})
        return YouTubeResponse(
            200,
            {
                "access_token": "test-access",
                "refresh_token": "test-refresh",
                "scope": " ".join(("https://www.googleapis.com/auth/youtube.upload",)),
                "token_type": "Bearer",
            },
            {},
        )

    def get_channel(self, *, access_token: str) -> YouTubeResponse:
        self.requests.append({"method": "GET", "endpoint": "channels.list"})
        return YouTubeResponse(200, {"items": [{"id": "channel-test", "snippet": {"title": "Test Creator"}}]}, {})

    def refresh_access_token(self, **kwargs) -> YouTubeResponse:
        self.requests.append({"method": "POST", "endpoint": "oauth.refresh"})
        return YouTubeResponse(200, {"access_token": "refreshed-access", "token_type": "Bearer"}, {})


def _http_error_code(status: int) -> str:
    return {401: "youtube.authentication_required", 403: "youtube.quota_or_forbidden", 429: "youtube.rate_limited"}.get(
        status, "youtube.api_error"
    )
