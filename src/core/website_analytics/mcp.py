"""MCP-style read-only query surface for website analytics."""

from __future__ import annotations

from typing import Any

from .service import WebsiteAnalyticsService


class WebsiteAnalyticsMCP:
    def __init__(self, service: WebsiteAnalyticsService) -> None:
        self.service = service

    def get_website_analytics_accounts(self) -> dict[str, Any]:
        payload = self.service.list_accounts()
        payload.update({"tool": "website_analytics.get_accounts", "read_only": True})
        return payload

    def get_website_analytics_sync_status(self, account_id: str) -> dict[str, Any]:
        payload = self.service.sync_status(account_id)
        payload.update({"tool": "website_analytics.get_sync_status", "read_only": True})
        return payload

    def get_website_analytics_quality(self, account_id: str) -> dict[str, Any]:
        payload = self.service.quality_report(account_id)
        payload.update({"tool": "website_analytics.get_quality", "read_only": True})
        return payload

    def get_content_funnel_provider_breakdown(self, content_item_id: str) -> dict[str, Any]:
        payload = self.service.provider_breakdown(content_item_id)
        payload.update({"tool": "website_analytics.get_provider_breakdown", "read_only": True})
        return payload

    def explain_attribution(self, account_id: str) -> dict[str, Any]:
        quality = self.service.quality_report(account_id)["quality"]
        return {
            "tool": "website_analytics.explain_attribution",
            "read_only": True,
            "account_id": account_id,
            "quality_status": quality["status"],
            "exact_attribution_rate": quality["exact_attribution_rate"],
            "unattributed_rate": quality["unattributed_rate"],
            "period": quality["period"],
        }


__all__ = ["WebsiteAnalyticsMCP"]
