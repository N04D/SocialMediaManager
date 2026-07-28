"""Provider-neutral protocols and safe HTTP facade for website analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import ProviderCapability, ProviderMetricObservation, WebsiteAnalyticsAccount, WebsiteAnalyticsQuery


@dataclass(frozen=True)
class SafeHttpRequest:
    method: str
    origin_reference_id: str
    url_path: str
    json_body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    auth_secret_reference_id: str = ""
    timeout_seconds: float = 10.0
    response_size_limit: int = 512 * 1024


@dataclass(frozen=True)
class SafeHttpResponse:
    status_code: int
    headers: dict[str, str]
    json_body: dict[str, Any] | None
    safe_error: str = ""


class SafeHttpFacade(Protocol):
    def send(self, request: SafeHttpRequest) -> SafeHttpResponse: ...


class WebsiteAnalyticsProvider(Protocol):
    provider_id: str
    provider_version: str
    provider_family: str
    execution_mode: str
    data_access: str

    def capabilities(self) -> tuple[ProviderCapability, ...]: ...

    def validate_account(self, account: WebsiteAnalyticsAccount) -> dict[str, Any]: ...

    def get_health(self, account: WebsiteAnalyticsAccount) -> dict[str, Any]: ...

    def plan_sync(self, account: WebsiteAnalyticsAccount, sync_type: str) -> list[WebsiteAnalyticsQuery]: ...

    def collect(
        self, account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery
    ) -> tuple[list[ProviderMetricObservation], dict[str, Any]]: ...

    def normalize(
        self, account: WebsiteAnalyticsAccount, query: WebsiteAnalyticsQuery, payload: dict[str, Any]
    ) -> list[ProviderMetricObservation]: ...

    def reconcile_cursor(self, cursor: str) -> dict[str, Any]: ...


class InMemorySafeHttpFacade:
    """Deterministic host-owned HTTP facade for fixtures and tests.

    It deliberately does not import direct HTTP clients. Production integration
    can bind the same request/response protocol to the existing host HTTP layer.
    """

    def __init__(self, responses: dict[str, SafeHttpResponse] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[SafeHttpRequest] = []

    def send(self, request: SafeHttpRequest) -> SafeHttpResponse:
        self.requests.append(request)
        if request.method != "POST":
            return SafeHttpResponse(405, {"content-type": "application/json"}, None, "method_not_allowed")
        return self.responses.get(
            request.url_path,
            SafeHttpResponse(404, {"content-type": "application/json"}, {"error": "not_found"}, "not_found"),
        )


__all__ = [
    "InMemorySafeHttpFacade",
    "SafeHttpFacade",
    "SafeHttpRequest",
    "SafeHttpResponse",
    "WebsiteAnalyticsProvider",
]
