"""Deterministic attribution for website analytics observations."""

from __future__ import annotations

from .models import ProviderMetricObservation, WebsiteAnalyticsAttribution, sanitize_dimensions


class WebsiteAnalyticsAttributionService:
    def attribute(
        self,
        observation_id: str,
        observation: ProviderMetricObservation,
        known_bindings: dict[str, dict[str, str]],
    ) -> WebsiteAnalyticsAttribution:
        dims = sanitize_dimensions(observation.dimensions)
        attribution_id = dims.get("smm_attribution_id", "")
        landing = dims.get("landing_url", "")
        campaign = dims.get("utm_campaign", "")
        content = observation.content_item_id or dims.get("utm_content", "")
        source = dims.get("utm_source", dims.get("source", ""))

        method = "unattributed"
        confidence = 0.0
        quality = "unattributed"
        binding: dict[str, str] = {}
        if attribution_id and attribution_id in known_bindings:
            method = "exact_attribution_id"
            confidence = 1.0
            quality = "complete"
            binding = known_bindings[attribution_id]
        elif campaign and content:
            method = "exact_campaign_and_content"
            confidence = 0.9
            quality = "complete"
        elif landing and observation.website_target_id:
            method = "exact_landing_url"
            confidence = 0.8
            quality = "partial"
        elif source and campaign:
            method = "source_and_campaign"
            confidence = 0.6
            quality = "partial"
        if (
            attribution_id
            and attribution_id in known_bindings
            and campaign
            and known_bindings[attribution_id].get("campaign_id", campaign) != campaign
        ):
            method = "conflicting"
            confidence = 0.0
            quality = "conflicting"

        return WebsiteAnalyticsAttribution(
            observation_id=observation_id,
            website_target_id=binding.get("website_target_id", observation.website_target_id),
            website_attempt_id=binding.get("website_attempt_id", observation.website_attempt_id),
            content_item_id=binding.get("content_item_id", observation.content_item_id or content),
            content_revision_id=binding.get("content_revision_id", observation.content_revision_id),
            campaign_id=binding.get("campaign_id", observation.campaign_id or campaign),
            source_social_target_id=binding.get("source_social_target_id", ""),
            source_social_attempt_id=binding.get("source_social_attempt_id", ""),
            attribution_id=attribution_id,
            attribution_method=method,
            confidence=confidence,
            quality_status=quality,
        )


__all__ = ["WebsiteAnalyticsAttributionService"]
