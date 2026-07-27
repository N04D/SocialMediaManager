"""Website metrics and content funnel readmodel."""

from __future__ import annotations

from collections import defaultdict

from .models import ContentFunnelPerformance, WebsiteMetricObservation

WEBSITE_METRICS = {
    "website.page_views",
    "website.unique_visitors",
    "website.engaged_visits",
    "website.average_read_time_seconds",
    "website.scroll_depth_average",
    "website.cta_clicks",
    "website.outbound_clicks",
    "website.conversions",
    "website.conversion_value",
    "website.referral_visits",
    "website.social_referral_visits",
}


class ContentFunnelBuilder:
    def build(
        self,
        *,
        content_item_id: str,
        content_revision_id: str,
        website_target_id: str,
        social_target_ids: tuple[str, ...],
        observations: tuple[WebsiteMetricObservation, ...],
    ) -> ContentFunnelPerformance:
        totals: dict[str, float] = defaultdict(float)
        source_breakdown: dict[str, float] = defaultdict(float)
        campaign_breakdown: dict[str, float] = defaultdict(float)
        for observation in observations:
            if (
                observation.content_item_id != content_item_id
                or observation.content_revision_id != content_revision_id
                or observation.website_target_id != website_target_id
            ):
                continue
            totals[observation.metric_name] += observation.value
            if source := observation.dimensions.get("source"):
                source_breakdown[source] += observation.value
            if observation.campaign:
                campaign_breakdown[observation.campaign] += observation.value
        visits = totals["website.page_views"]
        conversions = totals["website.conversions"]
        return ContentFunnelPerformance(
            content_item_id=content_item_id,
            content_revision_id=content_revision_id,
            website_target_id=website_target_id,
            social_target_ids=social_target_ids,
            impressions=totals["social.impressions"],
            social_engagement=totals["social.engagement"],
            link_clicks=totals["social.link_clicks"],
            website_visits=visits,
            engaged_visits=totals["website.engaged_visits"],
            cta_clicks=totals["website.cta_clicks"],
            conversions=conversions,
            conversion_value=totals["website.conversion_value"],
            conversion_rate=(conversions / visits) if visits else 0,
            source_breakdown=dict(source_breakdown),
            campaign_breakdown=dict(campaign_breakdown),
        )
