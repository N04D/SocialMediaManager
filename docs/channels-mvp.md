# Channel Plugin MVP

## Overview

The repository now has a hardened local-first channel-plugin slice for LinkedIn.
The core application remains file-backed.
Shared channel state lives under `studio_data/`, screenshots live under `outbox/channel_screenshots/`, and the dashboard stays the control plane while the worker owns Playwright.

The verified local flow is:

```text
Channel discovery
-> Connect / Check session
-> Approved derivative
-> Publish job
-> LinkedIn worker
-> Dry run or live publish
-> Published post record
-> Metrics job
-> Append-only metric snapshots
```

Real LinkedIn login, dry-run composer fill, live publish, URL capture, and live metrics refresh still require a manual operator run.
This document explains the hardened runtime and how to verify those steps safely.

## Folder Structure

```text
channels/
  linkedin/
    channel.manifest.json
    rules.yaml
    prompts/
      linkedin-post.md
    server/
      index.py
      actions.py
    worker/
      index.py
      browser.py
      connect.py
      session.py
      publish.py
      metrics.py
      runtime.py
      urls.py
    README.md
  instagram/
  substack/
  x/
  blog/
```

Supporting core modules:

- `channel_storage.py`: shared file locks and atomic JSON writes
- `channel_store.py`: channel persistence, atomic job claims, heartbeat storage
- `channel_registry.py`: manifest discovery and merged runtime status
- `channel_actions.py`: server-side derivative, approval, publish, and metrics guards
- `channel_dashboard.py`: generic channel UI helpers and LinkedIn verification panel
- `run_studio.py`: local launcher for dashboard plus persistent LinkedIn worker
- `tools/verify_linkedin_channel.py`: read-only manual verification report

## Manifest And Discovery

Each direct subfolder in `channels/` becomes a plugin candidate when it contains a valid `channel.manifest.json`.
Discovery is server-side and manifest-driven.
No plugin injects arbitrary frontend code in this MVP.

Discovery behavior:

- scans `channels/`
- validates required fields and supported values
- rejects duplicate plugin IDs
- records invalid plugins without crashing the application
- merges manifest metadata with persisted connection, worker, and profile state
- exposes the result through `GET /api/channels`

Supported plugin health states:

- `ready`
- `not_configured`
- `invalid_manifest`
- `missing_files`
- `worker_missing`
- `error`
- `disabled`

Placeholder plugins for `instagram`, `substack`, `x`, and `blog` appear in the Config UI but do not claim working publishing or connection support.

## Safe File-Store Architecture

The channel system remains JSON-backed in this phase.
The hardening layer is centralized in `channel_storage.py`.

Every shared store now uses one common pattern:

```python
with locked_json_store(path, default_factory=list, expect_type=list, lock_dir=LOCKS_DIR) as store:
    data = store.read()
    mutate(data)
    store.write(data)
```

Guarantees provided by this layer:

- cross-process file locking with `fcntl.flock`
- lock acquisition timeout with a controlled `LockTimeoutError`
- atomic writes through `NamedTemporaryFile` plus `os.replace`
- deterministic JSON serialization with sorted keys
- file and directory fsync where practical
- safe initialization when the store file is missing or empty
- corrupt JSON backup to `*.corrupt-<timestamp>.bak`
- no unlocked read-modify-write cycles in channel stores
- no stale in-memory state being written back over newer on-disk state

### Shared Store Paths

Channel data currently uses these files under `studio_data/`:

- `channel_connections.json`
- `content_derivatives.json`
- `approvals.json`
- `publish_jobs.json`
- `published_posts.json`
- `metric_jobs.json`
- `post_metric_snapshots.json`
- `worker_heartbeats.json`
- `channel_job_logs.json`

Shared lock files live under:

- `studio_data/locks/*.lock`

Examples:

- `studio_data/locks/publish_jobs.json.lock`
- `studio_data/locks/worker_heartbeats.json.lock`
- `studio_data/locks/linkedin.profile.lock`

### Locking Notes

- dashboard and worker respect the same lock files
- lock timeouts fail clearly instead of blocking forever
- process crashes do not permanently block the app because `flock` locks are released when the owning process exits
- lock owner metadata is local diagnostic information only and must not contain secrets
- the implementation is suitable for the supported local Linux environment; it is not presented as a cross-platform distributed lock manager

## Atomic Job Claim And Lease Behavior

Publish and metric jobs are now claimed atomically inside the shared store lock.
The worker never does an unlocked "read queued job -> mark running -> write" sequence.

The store now exposes atomic claim helpers conceptually equivalent to:

- `claim_next_publish_job(...)`
- `claim_next_metric_job(...)`

A claim operation:

- runs under the shared JSON store lock
- selects only eligible queued jobs
- assigns `claimed_by`
- sets `status=running`
- sets `started_at`
- increments `attempt_count`
- records `claimed_at`
- records `heartbeat_at`
- sets `lease_expires_at`
- returns the claimed job

The one-active-LinkedIn-publish rule is preserved at claim time, so two workers cannot claim two active LinkedIn publish jobs concurrently.

## Stale Job Recovery

A crashed worker should not leave safe jobs permanently stuck in `running`.
`channel_store.py` now applies bounded recovery rules when it scans for claimable jobs.

Safe recovery behavior:

- stale session-check-style or dry-run publish jobs may be moved back to `queued` when their lease expires and attempts remain
- stale metric jobs may be requeued under the same bounded attempt rules
- stale jobs over their attempt limit move to `failed`

Unsafe recovery behavior is blocked:

- a live publish job with evidence that submission may already have happened is not automatically requeued
- uncertain live outcomes become `manual_verification_required`
- automatic republish is intentionally blocked for `unknown_result`-style states

## Persistent Worker Lifecycle

The LinkedIn channel worker now supports a real persistent local mode.

Primary command:

```bash
venv/bin/python worker.py   --channel-jobs-only   --channel-id linkedin   --config config.json
```

Behavior:

1. starts and writes a `starting` heartbeat
2. transitions to `idle`
3. safely polls for eligible LinkedIn jobs
4. atomically claims one job at a time
5. keeps a lease and heartbeat fresh while the job is running
6. returns to `idle` when done
7. handles `SIGINT` and `SIGTERM`
8. marks itself `stopping` and then `offline` during graceful shutdown

Environment knobs:

```text
CHANNEL_WORKER_POLL_SECONDS=15
CHANNEL_WORKER_HEARTBEAT_SECONDS=10
CHANNEL_JOB_LEASE_SECONDS=180
CHANNEL_WORKER_STALE_SECONDS=90
```

The worker does not keep the Playwright profile open while idle.
Browser ownership is only acquired for connect, session check, publish, metrics, or disconnect work.

## Worker Heartbeats

Heartbeat records contain at least:

- `worker_id`
- `worker_type`
- `channel_id`
- `status`
- `started_at`
- `last_seen_at`
- `current_job_id`
- `current_job_type`
- `last_error`
- `process_id`

Statuses used by the UI and API:

- `starting`
- `idle`
- `busy`
- `stopping`
- `offline`
- `error`

Heartbeat freshness is computed from `CHANNEL_WORKER_STALE_SECONDS`.
An old heartbeat is shown as offline or stale instead of incorrectly looking online.

## Profile Ownership Rules

LinkedIn uses one persistent local Playwright profile.
The current project path still comes from `linkedin_user_data_dir` in `config.json`, which points at `linkedin_session/` in this repo.

One process may own that profile at a time.
A dedicated profile lock protects:

- connect
- check session
- publish
- metrics refresh
- disconnect and archive

If another process already owns the profile, the action surfaces `profile_busy` instead of opening a second Playwright context against the same profile.

## Connection And Session Behavior

Connection actions remain explicit and headed.
The dashboard does not publish directly.
It only launches the worker action.

Connect flow:

1. open `Config`
2. click `Connect`
3. the dashboard spawns `worker.py --channel-id linkedin --channel-action connect`
4. the worker opens a headed Playwright session
5. you log in manually
6. the worker verifies the authenticated LinkedIn feed state
7. the connection store is updated safely

Session checks and reconnects use the same profile ownership rules.
A previously stored `connected` state is not treated as proof that the current LinkedIn session is still valid.

Disconnect archives the current local profile into `studio_data/profile_archives/` instead of destructively deleting it.

## Derivatives, Review, And Approval

The Markdown editor remains the canonical source.
LinkedIn derivatives are stored separately and remain traceable through:

```text
source_document_id
-> derivative_id
-> publish_job_id
-> published_post_id
-> metric_snapshots
```

Allowed derivative workflow:

1. save canonical document
2. generate LinkedIn derivative
3. edit derivative
4. send for review
5. approve derivative
6. queue publish job

Server-side publish guards block publishing when:

- the derivative does not belong to the requested channel
- the derivative is not approved
- the approval record was revoked or is missing
- the channel is disconnected
- the plugin does not support publishing
- another active LinkedIn publish job already exists
- a confirmed published post already exists for the derivative

## Dry-Run Guarantees

Dry-run mode is intentionally safe.
It must never perform a real publish.

Supported worker environment flags:

```text
LINKEDIN_DRY_RUN=true
LINKEDIN_DEBUG=true
LINKEDIN_KEEP_BROWSER_OPEN_ON_ERROR=true
LINKEDIN_HEADLESS=false
```

Dry-run behavior:

- loads only an approved derivative
- verifies the LinkedIn session
- opens the LinkedIn composer
- fills the approved body
- compares the normalized composer content against the expected body
- records character counts and line-break checks
- captures a screenshot
- records structured dry-run result details
- never clicks the final submit button

Structured dry-run details include:

- `expected_character_count`
- `actual_character_count`
- `content_match`
- `line_breaks_match`
- `composer_detected`
- `final_submit_clicked: false`

The worker includes a final guard immediately before the submit click so dry-run mode is technically unable to submit by convention-breaking caller code.

## Live Publish Outcome Handling

Live publish still reuses the existing stable Playwright helpers from `pipeline.py`.
It was refactored into worker steps rather than rewritten from scratch.

Outcome handling aims to classify:

- `confirmed_success`
- `confirmed_failure`
- `unknown_result`

On success the worker stores, when available:

- confirmation signal used
- screenshot path
- external post URL
- external post ID
- publish timestamp

If the worker cannot confirm the result after a real submit attempt:

- it does not invent a URL
- it marks the job for manual verification
- it does not auto-retry live publish

### Manual URL Attachment

If you publish manually or a live publish reaches an uncertain result, attach the URL through the dashboard action.
The attach path accepts only normalized trusted LinkedIn post URLs.

Validation rules are centralized in `channels/linkedin/worker/urls.py`.
The worker rejects:

- non-LinkedIn hosts
- lookalike hosts
- unsupported LinkedIn paths
- arbitrary URLs provided straight to metrics collection

## Metrics Snapshot Behavior

Metrics are limited to trusted post URLs already stored in `published_posts`.
The worker never accepts arbitrary user URLs for scraping.

Metrics refresh behavior:

1. load a trusted published-post record
2. normalize and validate the stored LinkedIn URL
3. verify the current session
4. open only that trusted URL
5. parse visible numeric metrics deterministically
6. append a new snapshot
7. preserve raw visible labels and values
8. capture a screenshot

Important rules:

- missing metrics remain `None`
- visible zero remains numeric `0`
- failed refreshes do not overwrite prior successful snapshots
- successful refreshes append history instead of replacing it
- duplicate active manual metric jobs are reused instead of growing unbounded

Each snapshot may include deltas against the previous snapshot, such as:

- `delta_views`
- `delta_impressions`
- `delta_reactions`
- `delta_comments`
- `delta_reposts`
- `seconds_since_previous_snapshot`

## Job Logs And Screenshots

Channel job logs and screenshots are stored locally.

- logs: `studio_data/channel_job_logs.json`
- screenshots: `outbox/channel_screenshots/`

The dashboard exposes:

- latest screenshot links
- latest job log view
- latest worker state
- LinkedIn verification panel

Logs must not include passwords, cookies, session tokens, or full browser storage dumps.

## Local Launcher

The easiest local way to run the hardened MVP is:

```bash
venv/bin/python run_studio.py
```

Useful options:

```bash
venv/bin/python run_studio.py --config config.json --host 127.0.0.1 --port 8080
```

The launcher:

- starts the dashboard
- starts the persistent LinkedIn channel worker
- prefixes child logs
- forwards `SIGINT` and `SIGTERM`
- shuts both processes down cleanly
- exits non-zero if startup fails

The individual dashboard and worker commands remain available for debugging.

## Manual Verification Report

Use the read-only verification helper to see the current LinkedIn vertical-slice state:

```bash
venv/bin/python tools/verify_linkedin_channel.py --config config.json
```

It reports:

- `PASS`
- `FAIL`
- `NOT TESTED`
- `MANUAL ACTION REQUIRED`

It does not perform a live publish.

## Live Verification Checklist

Safe operator checklist:

1. Start the stack with `venv/bin/python run_studio.py`.
2. Open `http://127.0.0.1:8080/config` and confirm LinkedIn plus placeholders are listed.
3. Confirm the LinkedIn worker shows `idle` with a fresh heartbeat.
4. Click `Connect` and complete the manual LinkedIn login in the headed browser.
5. Use `Check session` and confirm the connection moves to `connected` with a recent verification time.
6. Save or open a canonical Markdown document.
7. Generate a LinkedIn derivative.
8. Review and approve it.
9. Run a dry-run publish first and inspect the screenshot plus structured result.
10. Only then attempt a live publish if you want a real post.
11. If live publish is uncertain, verify manually on LinkedIn before doing anything else.
12. Attach the real post URL if needed.
13. Run `Refresh metrics`.
14. Confirm a new metric snapshot is appended and previous snapshots remain intact.

## Known Limitations

- The system is still JSON/file-backed rather than database-backed.
- `fcntl`-based locking is appropriate for this local Linux workflow, not as a general distributed persistence layer.
- Real LinkedIn behavior still depends on the platform UI and may require selector maintenance over time.
- The legacy article-specific LinkedIn flow still exists beside the new derivative-based channel slice.
- Automatic scheduled metric refresh still depends on the existing worker model rather than a dedicated scheduler service.
- Manual operator verification is still required for real LinkedIn login, dry-run composer fidelity, live publish confirmation, URL capture, and live metrics collection.
