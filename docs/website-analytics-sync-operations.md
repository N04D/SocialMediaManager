# Website Analytics Sync Operations

Syncs use durable `website_analytics_sync_states` rows with status, cursor,
high watermark, correction window, attempt counts, and leases. The
`WebsiteAnalyticsSyncWorker` claims bounded batches and performs only read-only
provider queries.

Incremental syncs include a correction window for recently completed periods.
Changed provider values create append-only correction records rather than
in-place observation updates. Deduplication is based on source fingerprints and
query fingerprints.

Rate limits are recorded as provider state and move syncs out of tight retry
loops. Publication flows continue while analytics is delayed or degraded.
