"""Fake HTTP facade for website analytics provider certification."""

from __future__ import annotations

from src.core.website_analytics.provider import InMemorySafeHttpFacade, SafeHttpResponse

from .fixtures import plausible_fixture_responses


class FakeWebsiteAnalyticsHttpFacade(InMemorySafeHttpFacade):
    def __init__(self, responses: dict[str, SafeHttpResponse] | None = None) -> None:
        super().__init__(responses or plausible_fixture_responses())

    @property
    def provider_writes(self) -> int:
        return len([request for request in self.requests if request.url_path.startswith("/api/event")])


__all__ = ["FakeWebsiteAnalyticsHttpFacade"]
