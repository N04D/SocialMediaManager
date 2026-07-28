"""Read-only Plausible account doctor."""

from __future__ import annotations

from src.core.website_analytics.service import WebsiteAnalyticsService


def doctor(service: WebsiteAnalyticsService, account_id: str) -> dict:
    return service.doctor(account_id)


__all__ = ["doctor"]
