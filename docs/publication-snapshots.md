# Publication Snapshots

Snapshots are immutable JSON payloads created during preparation or queueing.

Included:

- content item ID
- revision ID and checksum
- variant ID and checksum
- content requirement version
- selected media relation IDs
- resolved asset and variant IDs
- media requirement version
- channel account, plugin, capability
- scheduled time and timezone
- snapshot contract version

Excluded:

- local paths
- storage references
- materialized paths
- provider secrets
- browser session data
- full remote payloads

The SHA-256 snapshot checksum supports stale detection, idempotency, audit, and evidence.

