# Mastodon Publishing

Text publishing uses `POST /api/v1/statuses`.

Allowed payload fields are `status`, `media_ids`, `visibility`, `sensitive`, `spoiler_text`, and `language`. The plugin never sends `scheduled_at`; scheduling remains local in the phase-14 scheduling framework.

The Mastodon `Idempotency-Key` is deterministic over publication target ID, snapshot checksum, execution generation, and channel account ID. A mutation-time timeout becomes `mutation_uncertain` and is not automatically retried.

Verification requires a status ID, global URI, safe URL, matching account identity, plausible created-at, and status retrieval.
