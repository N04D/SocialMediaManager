# Plausible Analytics Adapter v0.1

Documentation basis retrieved on 2026-07-28:

- Official Plausible Stats API reference: https://plausible.io/docs/stats-api
- Official Plausible Metrics definitions: https://plausible.io/docs/metrics-definitions

The adapter uses Plausible Stats API v2 only. The official Stats API reference
documents a single read endpoint, `POST /api/v2/query`, with API-key
authentication via an Authorization header and JSON responses containing
`results`, `meta`, and `query`. The docs explicitly direct write use cases to
the Events API and site-management use cases to the Sites API; this adapter does
neither.

Metric semantics:

- `visitors` maps to `website.unique_visitors` as a provider-defined unique
  estimate.
- `pageviews` maps to `website.page_views` as a sum.
- `visits` maps to `website.visits` as a sum.
- `visit_duration` maps to `website.average_visit_duration_seconds`; it is not
  treated as article read time.
- `time_on_page` remains `provider.plausible.time_on_page` unless explicitly
  used by a profile that understands the setup.
- `scroll_depth` maps to `website.scroll_depth_average`.
- `bounce_rate` remains provider-specific and is not called engagement rate.

The adapter does not use the Events API, create sites, delete sites, create
goals, install JavaScript, or send tracking events.
