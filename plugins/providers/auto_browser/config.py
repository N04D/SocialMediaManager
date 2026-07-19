from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class AutoBrowserConfig:
    enabled: bool = False
    base_url: str = ""
    bearer_token: str = ""
    operator_id: str = "social-media-manager"
    request_timeout: float = 15.0
    readiness_timeout: float = 5.0
    verify_tls: bool = True
    auth_profile_prefix: str = "smm"
    artifact_policy: str = "remote_reference"
    takeover_public_base_url: str = ""
    max_session_seconds: int = 1800
    expected_server_version: str = "1.3.1"

    @classmethod
    def from_app_config(cls, config: Any) -> AutoBrowserConfig:
        token_env = str(getattr(config, "auto_browser_bearer_token_env", "AUTO_BROWSER_BEARER_TOKEN") or "")
        return cls(
            enabled=bool(getattr(config, "auto_browser_enabled", False)),
            base_url=str(getattr(config, "auto_browser_base_url", "") or "").rstrip("/"),
            bearer_token=os.environ.get(token_env, "") if token_env else "",
            operator_id=str(getattr(config, "auto_browser_operator_id", "social-media-manager") or ""),
            request_timeout=float(getattr(config, "auto_browser_request_timeout", 15) or 15),
            readiness_timeout=float(getattr(config, "auto_browser_readiness_timeout", 5) or 5),
            verify_tls=bool(getattr(config, "auto_browser_verify_tls", True)),
            auth_profile_prefix=str(getattr(config, "auto_browser_auth_profile_prefix", "smm") or "smm"),
            artifact_policy=str(
                getattr(config, "auto_browser_artifact_policy", "remote_reference") or "remote_reference"
            ),
            takeover_public_base_url=str(getattr(config, "auto_browser_takeover_public_base_url", "") or "").rstrip(
                "/"
            ),
            max_session_seconds=int(getattr(config, "auto_browser_max_session_seconds", 1800) or 1800),
            expected_server_version=str(getattr(config, "auto_browser_expected_server_version", "1.3.1") or "1.3.1"),
        )

    def safe_base_url(self) -> str:
        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.hostname or ''}{(':' + str(parsed.port)) if parsed.port else ''}"

    def validate(self) -> list[str]:
        messages: list[str] = []
        if not self.enabled:
            return messages
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            messages.append("Auto Browser base URL is not configured.")
        if not self.operator_id.strip():
            messages.append("Auto Browser operator ID is not configured.")
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme == "http" and (parsed.hostname or "") not in local_hosts:
            messages.append("Auto Browser HTTP is only allowed for localhost.")
        if parsed.scheme == "https" and not self.verify_tls:
            messages.append("TLS verification is disabled for Auto Browser.")
        return messages
