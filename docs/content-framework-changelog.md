# Content Framework Changelog

## 0.1.0

- Added canonical `ContentItem` model.
- Added immutable `ContentRevision` records with deterministic checksums.
- Added explicit `ChannelContentVariant` records.
- Added generic channel content requirements and LinkedIn text requirements.
- Added `ContentService`.
- Added `PublicationPlan` and `PublicationTarget`.
- Added immutable planning snapshots and snapshot checksums.
- Added stale detection and idempotent queueing into existing publish jobs.
- Added lazy compatibility migration for legacy content/drafts.
- Added compact dashboard UI and JSON API routes for content and publication planning.

