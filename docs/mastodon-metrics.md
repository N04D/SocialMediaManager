# Mastodon Metrics

Mastodon metrics come from `GET /api/v1/statuses/{local_status_id}`.

Registered metrics:

- `favourites`: reaction, `reaction_count`, cumulative latest.
- `replies`: comment, `comment_count`, cumulative latest.
- `reblogs`: share, `share_count`, cumulative latest.
- `quotes`: optional feature-detected share metric.

The plugin does not register impressions, reach, views, clicks, or duration. Missing denominators are unavailable by channel, never zero.

Observations are sent through `AnalyticsIngestionService` as lifetime-to-date counters.
