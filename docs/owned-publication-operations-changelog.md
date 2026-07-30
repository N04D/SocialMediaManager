# Owned Publication Operations Changelog

## Phase 31

- Added GitHub CI evidence operator flow status to operations and release-check.
- Added exact current commit fields, run attempt, artifact ID, package,
  attestation, review, and promotion statuses.
- Preserved `remote_ci_status = artifact_not_imported` unless a concrete
  artifact is imported, verified, reviewed, and promoted.

## Phase 30

- Added managed secret readiness fields for vault, signer secret, GitHub
  credential, and real GitHub import status.
- Kept remote CI status at `artifact_not_imported` until a concrete artifact is
  imported.
- Kept phase 20.2 reported separately as not production-ready.

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

## 0.1.2

- Added production operations and release gates for owned-publication browser and worker certification.
- Added host-owned worker supervisor health, startup, cycle, heartbeat, and graceful shutdown reporting.
- Added managed SQLite backup, restore validation, backup retention preview, production readiness, support bundles, health endpoints, operations metrics, and operations dashboard.
- Added CI workflow definitions for browser/worker certification and owned-publication release gate.

## 0.1.3

- Added trusted signer readiness fields for host-owned certification evidence.
- Added CI artifact import readiness fields for exact imported artifact evidence.
- Kept phase 20.2 sandbox readiness separate and false until independently certified.


## Phase 32

Added safe onboarding summaries to operations/readiness documentation and kept production readiness separate from alpha onboarding status. Phase 20.2 external sandbox certification remains separately blocked.
