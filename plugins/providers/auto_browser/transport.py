from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from .config import AutoBrowserConfig
from .errors import (
    AutoBrowserConnectionError,
    AutoBrowserNotReadyError,
    AutoBrowserRateLimitError,
    AutoBrowserResponseError,
    AutoBrowserSessionNotFoundError,
    AutoBrowserTimeoutError,
    AutoBrowserUnauthorizedError,
)

MAX_RESPONSE_BYTES = 2_000_000


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlparse(req.full_url)
        new = urllib.parse.urlparse(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc) and req.headers.get("Authorization"):
            raise AutoBrowserResponseError("Auto Browser redirect changed origin while authorization was present.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AutoBrowserTransport(Protocol):
    def health(self) -> dict[str, Any]: ...

    def ready(self) -> dict[str, Any]: ...

    def server_info(self) -> dict[str, Any]: ...

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_session(self, remote_session_id: str) -> dict[str, Any]: ...

    def list_sessions(self) -> list[dict[str, Any]]: ...

    def close_session(self, remote_session_id: str) -> dict[str, Any]: ...

    def observe(self, remote_session_id: str, *, limit: int = 80, preset: str = "normal") -> dict[str, Any]: ...

    def navigate(self, remote_session_id: str, url: str) -> dict[str, Any]: ...

    def perform_action(
        self, remote_session_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def screenshot(self, remote_session_id: str, *, full_page: bool = True) -> dict[str, Any]: ...

    def evaluate(self, remote_session_id: str, script: str, arg: Any | None = None) -> Any: ...

    def create_takeover(self, remote_session_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def save_auth_profile(self, remote_session_id: str, profile_name: str) -> dict[str, Any]: ...

    def list_auth_profiles(self) -> list[dict[str, Any]]: ...

    def get_auth_profile(self, profile_name: str) -> dict[str, Any]: ...

    def delete_auth_profile(self, profile_name: str) -> dict[str, Any]: ...


@dataclass
class AutoBrowserHttpTransport:
    config: AutoBrowserConfig

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")

    def ready(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/readyz", timeout=self.config.readiness_timeout)
        except AutoBrowserNotReadyError:
            return self._request("GET", "/readiness", timeout=self.config.readiness_timeout)

    def server_info(self) -> dict[str, Any]:
        return self._request("GET", "/version")

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/sessions", payload)

    def get_session(self, remote_session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{self._quote(remote_session_id)}")

    def list_sessions(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/sessions")
        return result if isinstance(result, list) else list(result.get("sessions") or [])

    def close_session(self, remote_session_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/sessions/{self._quote(remote_session_id)}")

    def observe(self, remote_session_id: str, *, limit: int = 80, preset: str = "normal") -> dict[str, Any]:
        return self._request(
            "GET",
            f"/sessions/{self._quote(remote_session_id)}/observe?limit={int(limit)}&preset={self._quote(preset)}",
        )

    def navigate(self, remote_session_id: str, url: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{self._quote(remote_session_id)}/actions/navigate", {"url": url})

    def perform_action(
        self, remote_session_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        action_path = {
            "click": "click",
            "fill": "type",
            "clear": "type",
            "keyboard_press": "press",
            "keyboard_insert_text": "type",
            "hover": "hover",
            "upload": "upload",
            "wait": "wait",
            "reload": "reload",
            "go_back": "go-back",
            "scroll": "scroll",
        }.get(action, action)
        return self._request(
            "POST",
            f"/sessions/{self._quote(remote_session_id)}/actions/{action_path}",
            payload or {},
        )

    def screenshot(self, remote_session_id: str, *, full_page: bool = True) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/sessions/{self._quote(remote_session_id)}/screenshot",
            {"full_page": bool(full_page)},
        )

    def evaluate(self, remote_session_id: str, script: str, arg: Any | None = None) -> Any:
        result = self._request(
            "POST",
            f"/sessions/{self._quote(remote_session_id)}/actions/execute",
            {"script": script, "arg": arg},
        )
        return result.get("result") if isinstance(result, dict) and "result" in result else result

    def create_takeover(self, remote_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{self._quote(remote_session_id)}/takeover", payload)

    def save_auth_profile(self, remote_session_id: str, profile_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/sessions/{self._quote(remote_session_id)}/auth-profiles",
            {"profile_name": profile_name},
        )

    def list_auth_profiles(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/auth-profiles")
        return result if isinstance(result, list) else list(result.get("profiles") or [])

    def get_auth_profile(self, profile_name: str) -> dict[str, Any]:
        return self._request("GET", f"/auth-profiles/{self._quote(profile_name)}")

    def delete_auth_profile(self, profile_name: str) -> dict[str, Any]:
        return self._request("DELETE", f"/auth-profiles/{self._quote(profile_name)}")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        if not self.config.base_url:
            raise AutoBrowserConnectionError("Auto Browser base URL is not configured.")
        url = self.config.base_url.rstrip("/") + path
        data = None
        headers = {
            "Accept": "application/json",
            "X-Operator-ID": self.config.operator_id,
            "X-Request-ID": uuid4().hex,
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        context = None
        if urllib.parse.urlparse(url).scheme == "https" and not self.config.verify_tls:
            context = ssl._create_unverified_context()
        try:
            opener = urllib.request.build_opener(_SafeRedirectHandler())
            if context is not None:
                opener.add_handler(urllib.request.HTTPSHandler(context=context))
            with opener.open(request, timeout=timeout or self.config.request_timeout) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise AutoBrowserResponseError("Auto Browser response is too large.")
                if not content:
                    return {}
                return json.loads(content.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except TimeoutError as exc:
            raise AutoBrowserTimeoutError("Auto Browser request timed out.") from exc
        except urllib.error.URLError as exc:
            raise AutoBrowserConnectionError("Auto Browser controller is unreachable.") from exc
        except json.JSONDecodeError as exc:
            raise AutoBrowserResponseError("Auto Browser returned invalid JSON.") from exc

    def _raise_http_error(self, exc: urllib.error.HTTPError) -> None:
        status = int(exc.code)
        if status in {401, 403}:
            raise AutoBrowserUnauthorizedError("Auto Browser authentication failed.") from exc
        if status == 404:
            raise AutoBrowserSessionNotFoundError("Auto Browser session was not found.") from exc
        if status == 409:
            raise AutoBrowserNotReadyError("Auto Browser is not ready for this operation.") from exc
        if status == 429:
            raise AutoBrowserRateLimitError("Auto Browser rate limit was reached.") from exc
        if status >= 500:
            raise AutoBrowserConnectionError("Auto Browser controller returned a server error.") from exc
        raise AutoBrowserResponseError("Auto Browser request failed.", details={"status": status}) from exc

    @staticmethod
    def _quote(value: str) -> str:
        return urllib.parse.quote(str(value), safe="")
