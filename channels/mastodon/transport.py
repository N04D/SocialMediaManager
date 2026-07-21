from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .errors import MastodonApiError, MastodonRateLimitError, MastodonResponseValidationError
from .instance import validate_redirect_origin


@dataclass
class MastodonApiResponse:
    status: int
    json_body: Any
    headers: dict[str, str] = field(default_factory=dict)
    rate_limit: dict[str, Any] = field(default_factory=dict)


class MastodonApiTransport:
    def request(self, origin: str, method: str, path: str, **kwargs) -> MastodonApiResponse:
        raise NotImplementedError

    def get_json(self, origin: str, path: str, **kwargs):
        response = self.request(origin, "GET", path, **kwargs)
        return response.json_body, {"rate_limit": response.rate_limit, "status": response.status}

    def post_form(self, origin: str, path: str, data: dict[str, Any], **kwargs):
        response = self.request(origin, "POST", path, form=data, **kwargs)
        return response.json_body, {"rate_limit": response.rate_limit, "status": response.status}

    def post_multipart(
        self, origin: str, path: str, fields: dict[str, Any], files: dict[str, tuple[str, bytes, str]], **kwargs
    ):
        response = self.request(origin, "POST", path, fields=fields, files=files, multipart=True, **kwargs)
        return response.json_body, {"rate_limit": response.rate_limit, "status": response.status}

    def delete(self, origin: str, path: str, **kwargs):
        response = self.request(origin, "DELETE", path, **kwargs)
        return response.json_body, {"rate_limit": response.rate_limit, "status": response.status}


class HttpMastodonApiTransport(MastodonApiTransport):
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_response_bytes: int = 1_000_000,
        allow_localhost_http: bool = False,
        resolver: Any = None,
    ):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_response_bytes = max_response_bytes
        self.allow_localhost_http = allow_localhost_http
        self.resolver = resolver

    def request(self, origin: str, method: str, path: str, **kwargs) -> MastodonApiResponse:
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{origin}{path}"
        headers = {"Accept": "application/json", "User-Agent": "SocialMediaManager Mastodon/0.1.0"}
        token = str(kwargs.get("access_token") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        extra_headers = dict(kwargs.get("headers") or {})
        for key, value in extra_headers.items():
            if key.lower() != "authorization":
                headers[str(key)] = str(value)
        body = None
        if kwargs.get("multipart"):
            body, content_type = _multipart_body(kwargs.get("fields") or {}, kwargs.get("files") or {})
            headers["Content-Type"] = content_type
        elif "form" in kwargs:
            body = urllib.parse.urlencode(kwargs.get("form") or {}).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        opener = urllib.request.build_opener(_NoCrossOriginRedirect(origin, self.allow_localhost_http, self.resolver))
        try:
            with opener.open(request, timeout=self.read_timeout) as response:
                return self._read_response(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise MastodonRateLimitError(
                    "mastodon.rate_limited",
                    "Mastodon rate limit reached.",
                    retryable=True,
                    http_status=429,
                    details={"retry_after": exc.headers.get("Retry-After", "")},
                ) from exc
            raise MastodonApiError(
                "mastodon.api_error", "Mastodon API returned an error.", http_status=exc.code
            ) from exc
        except TimeoutError as exc:
            raise MastodonApiError("mastodon.timeout", "Mastodon API request timed out.", retryable=True) from exc
        except OSError as exc:
            raise MastodonApiError("mastodon.network_error", "Mastodon API request failed.", retryable=True) from exc

    def _read_response(self, response) -> MastodonApiResponse:
        content_type = str(response.headers.get("Content-Type") or "")
        data = response.read(self.max_response_bytes + 1)
        if len(data) > self.max_response_bytes:
            raise MastodonResponseValidationError(
                "mastodon.response_oversized", "Mastodon response exceeded the size limit."
            )
        if "json" not in content_type:
            raise MastodonResponseValidationError("mastodon.response_not_json", "Mastodon response was not JSON.")
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MastodonResponseValidationError(
                "mastodon.response_malformed_json", "Mastodon response JSON was malformed."
            ) from exc
        headers = {key: str(value) for key, value in response.headers.items()}
        return MastodonApiResponse(
            status=response.status, json_body=payload, headers=_safe_headers(headers), rate_limit=_rate_limit(headers)
        )


class _NoCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: str, allow_localhost_http: bool, resolver: Any):
        self.origin = origin
        self.allow_localhost_http = allow_localhost_http
        self.resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_redirect_origin(
            self.origin, newurl, allow_localhost_http=self.allow_localhost_http, resolver=self.resolver
        )
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            new is not None
            and urllib.parse.urlparse(newurl).scheme + "://" + urllib.parse.urlparse(newurl).netloc != self.origin
        ):
            new.remove_header("Authorization")
        return new


class FakeMastodonApiTransport(MastodonApiTransport):
    def __init__(self, routes: dict[tuple[str, str], Any] | None = None):
        self.routes = routes or {}
        self.requests: list[dict[str, Any]] = []

    def request(self, origin: str, method: str, path: str, **kwargs) -> MastodonApiResponse:
        self.requests.append({"origin": origin, "method": method, "path": path, "kwargs": _redacted(kwargs)})
        result = self.routes.get((method, path))
        if callable(result):
            result = result(origin=origin, method=method, path=path, **kwargs)
        if result is None:
            result = {}
        if isinstance(result, MastodonApiResponse):
            return result
        if isinstance(result, Exception):
            raise result
        return MastodonApiResponse(status=200, json_body=result, headers={}, rate_limit={})


def _multipart_body(fields: dict[str, Any], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"smmmastodon{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for key, (filename, data, mime_type) in files.items():
        safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in filename)[:120] or "upload"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"; filename="{safe_name}"\r\n'.encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _rate_limit(headers: dict[str, str]) -> dict[str, Any]:
    return {
        "limit": headers.get("X-RateLimit-Limit", ""),
        "remaining": headers.get("X-RateLimit-Remaining", ""),
        "reset": headers.get("X-RateLimit-Reset", ""),
    }


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in {"x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"}
    }


def _redacted(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: ("[REDACTED]" if "token" in key.lower() else _redacted(value)) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_redacted(item) for item in payload]
    return payload
