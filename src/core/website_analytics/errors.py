"""Safe errors for website analytics collection."""

from __future__ import annotations


class WebsiteAnalyticsError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class WebsiteAnalyticsConfigurationError(WebsiteAnalyticsError):
    pass


class WebsiteAnalyticsProviderError(WebsiteAnalyticsError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        needs_configuration: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(code, message, details)
        self.retryable = retryable
        self.needs_configuration = needs_configuration


__all__ = [
    "WebsiteAnalyticsConfigurationError",
    "WebsiteAnalyticsError",
    "WebsiteAnalyticsProviderError",
]
