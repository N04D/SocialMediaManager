# Owned Publication Operations Changelog

## 0.1.0

- Added SQLite-backed owned-publication repositories and migrations.
- Added durable drafts, revisions, variants, snapshots, plans, targets, dependencies, schedules, occurrences, timeline events, evidence, reconciliation, campaigns, observations, readmodels, and audit records.
- Added lease-safe reconciliation and restart recovery.
- Added storage, recovery, readmodel, campaign, and reconciliation API/CLI operations.
- Documented that phase 20.2 remains separately blocked.

## 0.1.1

- Added phase-23.1 real browser certification for the owned-publication workspace against a temporary dashboard server and SQLite database.
- Added two-context browser concurrency coverage for stale draft autosave conflicts.
- Added bounded worker certification for concurrent occurrence and reconciliation claims, heartbeat, lease expiry, reclaim, and no-blind-retry behavior.
- Documented that no CI browser certification job exists until a suitable Chromium-capable runner is configured.
