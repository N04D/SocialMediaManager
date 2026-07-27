# Owned Publication Browser Tests

Phase 23 adds a project-conformant browser-style HTTP test against the real dashboard server and a temporary SQLite database. It creates and autosaves an article, reloads through API routes, verifies concurrency conflict handling, restarts the server, and confirms durable state remains.

The test uses a temporary content directory and deterministic services. It does not use production credentials, production social accounts, external network calls, or the repository `content/` and `drafts/` directories.

## Phase 23.1 Certification

Phase 23.1 upgrades the browser proof from route integration to real browser automation. The certification uses Playwright for Python against a temporary `ThreadingHTTPServer`, a temporary SQLite database, synthetic fixture identities, and the existing dashboard routes. The browser is launched headless against localhost only; if the Playwright-managed browser is unavailable, the test uses a system Chromium executable such as `/snap/bin/chromium`.

Run the browser certification with:

```bash
python -m unittest tests.test_owned_publication_real_browser_phase23_1 -v
python -m unittest tests.test_owned_publication_browser_concurrency_phase23_1 -v
```

The real browser flow verifies DOM rendering, JavaScript autosave, debounce behavior, reload persistence, server restart persistence, publication plan controls, dependency display, timeline and evidence views, reconciliation status updates, funnel rendering, sanitized Markdown preview, keyboard tabs, labels, live statuses, and conflict handling across two browser contexts.

Worker certification uses the production SQLite claim and lease methods through a bounded host-owned worker loop. The execution model is `thread`, matching the local worker architecture in this repository. The worker loop performs read-only checks and pre-mutation dependency evaluation only; it does not retry uncertain Git or social mutations.

Run the worker certification with:

```bash
python -m unittest tests.test_owned_publication_worker_concurrency_phase23_1 -v
python -m unittest tests.test_owned_publication_worker_recovery_phase23_1 -v
```

The worker tests start two real worker threads against one SQLite database, verify atomic occurrence and reconciliation claims, prove lease heartbeat and expiry/reclaim behavior, and check that duplicate events, duplicate evidence, and blind mutation retries are not produced.

No CI browser job is configured in this repository yet. The local certification commands above are the authoritative phase-23.1 entrypoint until a suitable CI runner with Chromium is added.
