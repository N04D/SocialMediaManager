# Analytics MCP

Phase 15 exposes read-only analytics helpers for MCP-style use:

- `analytics.list_metrics`
- `analytics.get_publication_performance`
- `analytics.get_content_performance`
- `analytics.compare_revisions`
- `analytics.compare_variants`
- `analytics.get_media_performance`
- `analytics.get_campaign_performance`
- `analytics.get_channel_performance`
- `analytics.get_freshness`

Tools read safe readmodels only. They do not start browser sessions, scrape metrics, publish content, correct observations, or mutate attribution.

Responses include subject, period where applicable, dimensions, metrics, derived metrics, sample size, freshness, completeness, definition versions, observation type, and comparison validity.
