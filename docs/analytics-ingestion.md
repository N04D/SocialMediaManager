# Analytics Ingestion

Channel runtimes provide `ChannelMetricObservationInput` records:

- remote publication ID
- local publication ID
- metric key
- value
- observed timestamp
- measurement window
- source version
- safe evidence reference
- limited metadata

`AnalyticsIngestionService` resolves definitions, validates values, resolves attribution, computes observation keys, deduplicates, and persists immutable observations.

Existing LinkedIn metric scraping still owns navigation and metric extraction. It now sends captured snapshots to the generic analytics ingestion service after saving the legacy snapshot.

Collection runs are bounded and record counts, duplicates, failures, source version, watermarks, and safe error codes.
