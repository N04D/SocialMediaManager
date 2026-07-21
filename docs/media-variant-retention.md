# Media Variant Retention

Phase 11 retention is preview-first and variant-only.

`MediaRetentionPolicy` includes workspace, target type, unused age, failed variant age, deleted asset age, historical publication preservation, latest-variant preservation, dry-run requirement, enabled flag, and timestamps.

Retention preview is read-only. It reports asset ID, variant ID, status, reason, last used time, relation count, publication usage count, estimated bytes, blockers, and proposed action. It never includes storage references or object paths.

Retention plans capture candidates and require explicit confirmation before execution. Execution revalidates candidates, skips changed candidates, soft-deletes variants only, writes audit/events, and never physically deletes original assets or storage objects.

Blockers include active relations, historical publication usage, active materialization, processing status, pins, unknown ownership, repository inconsistency, source asset issues, and recent use.

Pins are supported on assets and variants with `retention_pinned`, `pinned_at`, `pinned_by`, and `pin_reason`.
