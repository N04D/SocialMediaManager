# Metric Definitions

Metric definitions describe what a value means before observations are accepted.

Each definition contains channel, key, version, value type, unit, semantic type, aggregation semantics, comparable group, cumulative behavior, denominator hints, and source scope.

LinkedIn registers only fields captured by the existing metrics flow:

- `impressions`
- `views`
- `reactions`
- `comments`
- `reposts`
- `shares`
- `clicks`

Definitions are versioned. Re-registering the same key/version with different semantics is rejected. Cross-channel comparison is allowed only when comparable group, unit, aggregation behavior, source scope, and known definition versions are compatible.
