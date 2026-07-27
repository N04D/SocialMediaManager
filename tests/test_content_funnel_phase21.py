from __future__ import annotations

import unittest

from channels.markdown_website.metrics import WEBSITE_METRICS, ContentFunnelBuilder
from channels.markdown_website.models import WebsiteMetricObservation


class ContentFunnelPhase21Tests(unittest.TestCase):
    def test_website_social_and_conversion_metrics_bind_to_revision(self) -> None:
        observations = (
            WebsiteMetricObservation("social.impressions", 1000, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("social.engagement", 50, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("social.link_clicks", 25, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation(
                "website.page_views",
                20,
                "content-1",
                "revision-1",
                "target-website",
                campaign="campaign-1",
                dimensions={"source": "linkedin"},
            ),
            WebsiteMetricObservation("website.engaged_visits", 12, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("website.cta_clicks", 4, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("website.conversions", 2, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("website.conversion_value", 99, "content-1", "revision-1", "target-website"),
            WebsiteMetricObservation("website.page_views", 999, "content-1", "other-revision", "target-website"),
        )
        funnel = ContentFunnelBuilder().build(
            content_item_id="content-1",
            content_revision_id="revision-1",
            website_target_id="target-website",
            social_target_ids=("target-linkedin", "target-mastodon"),
            observations=observations,
        )
        self.assertEqual(funnel.link_clicks, 25)
        self.assertEqual(funnel.website_visits, 20)
        self.assertEqual(funnel.conversions, 2)
        self.assertEqual(funnel.conversion_rate, 0.1)
        self.assertEqual(funnel.source_breakdown["linkedin"], 20)
        self.assertIn("website.cta_clicks", WEBSITE_METRICS)


if __name__ == "__main__":
    unittest.main()
