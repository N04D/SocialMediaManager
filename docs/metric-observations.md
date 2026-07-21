# Metric Observations

`MetricObservation` is immutable source data for analytics.

It records publication identity, channel/account, metric definition, value, observation time, measurement window, source version, source run, status, and a deterministic observation key.

## Semantics

- Cumulative: a platform-reported lifetime total at a time.
- Delta: a derived change between compatible observations.
- Gauge: a point-in-time value such as a rate.
- Event count: a count within an explicit window.

Cumulative snapshots from the same publication are not summed over time. Deltas are derived only when definition, scope, publication, and time ordering are compatible. Negative cumulative deltas become warnings, not normal growth.

Corrections create a new observation and a correction record. Original values are not silently overwritten.
