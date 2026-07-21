# Derived Metrics

Derived metrics are versioned and limited to explicit formulas:

- sum of compatible metrics
- ratio
- percentage
- delta
- rate per exposure
- rate per reach when available

Phase 15 registers:

- `engagement_rate_by_impressions`
- `engagement_rate_by_reach`

Engagement rate is null when denominator data is missing or zero. Missing denominators are not shown as `0%`.

Rates must be aggregated with denominators where possible. The framework does not use simple averages of percentages when denominator sizes differ materially.
