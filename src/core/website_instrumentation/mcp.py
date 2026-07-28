"""MCP-style query surface for website instrumentation."""

from __future__ import annotations

from typing import Any

from .service import WebsiteInstrumentationService


class WebsiteInstrumentationMCP:
    def __init__(self, service: WebsiteInstrumentationService | None = None) -> None:
        self.service = service or WebsiteInstrumentationService()

    def get_website_instrumentation_config(self, config_id: str) -> dict[str, Any]:
        payload = self.service.config(config_id)
        payload.update({"tool": "website_instrumentation.get_config"})
        return payload

    def get_publication_instrumentation_manifest(self, config_id: str) -> dict[str, Any]:
        return self.service.preview_manifest(config_id)

    def get_website_instrumentation_verification(self, config_id: str) -> dict[str, Any]:
        return self.service.verify(config_id)

    def get_website_instrumentation_quality(self, config_id: str) -> dict[str, Any]:
        return {"quality": self.service.quality(config_id)}

    def get_instrumentation_mapping_drift(self, config_id: str) -> dict[str, Any]:
        return {"drift": self.service.drift(config_id)}

    def get_cta_instrumentation_coverage(self, config_id: str) -> dict[str, Any]:
        return {"coverage": self.service.quality(config_id)["cta_coverage"]}

    def get_conversion_instrumentation_coverage(self, config_id: str) -> dict[str, Any]:
        return {"coverage": self.service.quality(config_id)["conversion_coverage"]}

    def explain_missing_funnel_data(self, config_id: str) -> dict[str, Any]:
        quality = self.service.quality(config_id)
        return {
            "config_id": config_id,
            "reason": "mapping drift or provider data has not been observed"
            if quality["overall_status"] != "complete"
            else "",
            "quality": quality,
            "no_causality_claim": True,
        }


__all__ = ["WebsiteInstrumentationMCP"]
