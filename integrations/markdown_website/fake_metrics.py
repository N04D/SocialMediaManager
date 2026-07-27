"""Deterministic website metrics fixture."""

from channels.markdown_website.models import WebsiteMetricObservation


def observations() -> tuple[WebsiteMetricObservation, ...]:
    return (
        WebsiteMetricObservation("website.page_views", 10, "content-1", "revision-1", "target-website"),
        WebsiteMetricObservation("website.engaged_visits", 6, "content-1", "revision-1", "target-website"),
        WebsiteMetricObservation("website.cta_clicks", 2, "content-1", "revision-1", "target-website"),
        WebsiteMetricObservation("website.conversions", 1, "content-1", "revision-1", "target-website"),
    )
