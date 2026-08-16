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
CAPTIONS_ENDPOINT = "https://www.googleapis.com/youtube/v3/captions"
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

    def list_captions(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        raise NotImplementedError

    def download_caption(self, *, caption_id: str, access_token: str, tfmt: str = "vtt") -> bytes:
        raise NotImplementedError

    def exchange_code(self, *, code: str, client_id: str, client_secret: str, redirect_uri: str) -> YouTubeResponse:
        raise NotImplementedError

    def get_channel(self, *, access_token: str) -> YouTubeResponse:
        raise NotImplementedError

    def get_channel_uploads_playlist(
        self, *, channel_id: str = "", access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
        raise NotImplementedError

    def list_playlist_items(
        self, *, playlist_id: str, page_token: str = "", max_results: int = 50, access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
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

    def _request_bytes(
        self,
        url: str,
        *,
        method: str,
        access_token: str = "",
        max_bytes: int = 2_000_000,
    ) -> bytes:
        headers = {"Accept": "*/*", "User-Agent": "SocialMediaManager YouTube/0.1.0"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise YouTubeChannelError("youtube.response_too_large", "YouTube API response exceeded limit.")
                return raw
        except urllib.error.HTTPError as exc:
            raise YouTubeChannelError(
                _http_error_code(exc.code),
                "YouTube API request failed.",
                {"http_status": exc.code},
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

    def list_captions(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        query = urllib.parse.urlencode({"part": "id,snippet", "videoId": video_id})
        return self._request(f"{CAPTIONS_ENDPOINT}?{query}", method="GET", access_token=access_token)

    def download_caption(self, *, caption_id: str, access_token: str, tfmt: str = "vtt") -> bytes:
        query = urllib.parse.urlencode({"id": caption_id, "tfmt": tfmt})
        return self._request_bytes(f"{CAPTIONS_ENDPOINT}/{caption_id}?{query}", method="GET", access_token=access_token)

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

    def get_channel_uploads_playlist(
        self, *, channel_id: str = "", access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
        params: dict[str, str] = {"part": "contentDetails,snippet"}
        if channel_id:
            params["id"] = channel_id
        else:
            params["mine"] = "true"
        if api_key:
            params["key"] = api_key
        query = urllib.parse.urlencode(params)
        endpoint = f"{VIDEO_ENDPOINT.rsplit('/', 1)[0]}/channels"
        return self._request(f"{endpoint}?{query}", method="GET", access_token=access_token)

    def list_playlist_items(
        self, *, playlist_id: str, page_token: str = "", max_results: int = 50, access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
        params: dict[str, str] = {
            "part": "snippet,contentDetails,status",
            "playlistId": playlist_id,
            "maxResults": str(min(max_results, 50)),
        }
        if page_token:
            params["pageToken"] = page_token
        if api_key:
            params["key"] = api_key
        query = urllib.parse.urlencode(params)
        endpoint = f"{VIDEO_ENDPOINT.rsplit('/', 1)[0]}/playlistItems"
        return self._request(f"{endpoint}?{query}", method="GET", access_token=access_token)

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
        self.channels: list[dict[str, Any]] = [
            {
                "id": "channel-test",
                "snippet": {"title": "Test Creator"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU_channel_test"}},
            }
        ]
        self.playlist_items: dict[str, list[dict[str, Any]]] = {}
        self.videos_by_id: dict[str, dict[str, Any]] = {}
        self.captions_by_video_id: dict[str, list[dict[str, Any]]] = {}
        self.caption_downloads: dict[str, bytes] = {}
        self.error_override: Exception | None = None

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
        if self.error_override:
            raise self.error_override
        if video_id in self.videos_by_id:
            raw_item = self.videos_by_id[video_id]
            if raw_item is None:
                return YouTubeResponse(200, {"items": []}, {})
            return YouTubeResponse(200, {"items": [raw_item]}, {})

        return YouTubeResponse(
            200,
            {
                "items": [
                    {
                        "id": video_id,
                        "snippet": {
                            "title": f"Title for {video_id}",
                            "description": f"Description for {video_id}",
                            "channelId": "channel-test",
                            "publishedAt": "2026-08-10T00:00:00Z",
                        },
                        "contentDetails": {"duration": "PT5M"},
                        "status": {"privacyStatus": self.observed_privacy},
                        "processingDetails": {"processingStatus": self.processing_status},
                    }
                ]
            },
            {},
        )

    def list_captions(self, *, video_id: str, access_token: str) -> YouTubeResponse:
        self.requests.append({"method": "GET", "endpoint": "captions.list", "video_id": video_id})
        if self.error_override:
            raise self.error_override
        return YouTubeResponse(200, {"items": list(self.captions_by_video_id.get(video_id, []))}, {})

    def download_caption(self, *, caption_id: str, access_token: str, tfmt: str = "vtt") -> bytes:
        self.requests.append({"method": "GET", "endpoint": "captions.download", "caption_id": caption_id, "tfmt": tfmt})
        if self.error_override:
            raise self.error_override
        if caption_id not in self.caption_downloads:
            raise YouTubeChannelError("youtube.caption_not_found", "Caption track was not found.")
        return self.caption_downloads[caption_id]

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
        return YouTubeResponse(200, {"items": self.channels}, {})

    def get_channel_uploads_playlist(
        self, *, channel_id: str = "", access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
        self.requests.append({"method": "GET", "endpoint": "channels.list", "channel_id": channel_id})
        if self.error_override:
            raise self.error_override
        matched = [c for c in self.channels if not channel_id or c["id"] == channel_id]
        return YouTubeResponse(200, {"items": matched}, {})

    def list_playlist_items(
        self, *, playlist_id: str, page_token: str = "", max_results: int = 50, access_token: str = "", api_key: str = ""
    ) -> YouTubeResponse:
        self.requests.append({
            "method": "GET",
            "endpoint": "playlistItems.list",
            "playlist_id": playlist_id,
            "page_token": page_token,
            "max_results": max_results,
        })
        if self.error_override:
            raise self.error_override
        items = self.playlist_items.get(playlist_id, [])
        offset = int(page_token) if page_token and page_token.isdigit() else 0
        paged = items[offset : offset + max_results]
        next_token = str(offset + max_results) if offset + max_results < len(items) else ""
        payload = {"items": paged}
        if next_token:
            payload["nextPageToken"] = next_token
        return YouTubeResponse(200, payload, {})


def _http_error_code(status: int) -> str:
    return {401: "youtube.authentication_required", 403: "youtube.quota_or_forbidden", 429: "youtube.rate_limited"}.get(
        status, "youtube.api_error"
    )
