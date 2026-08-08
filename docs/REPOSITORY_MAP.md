# Repository Map

This map highlights the important repository areas.

```text
.
├── dashboard.py                  # Local dashboard HTTP server and UI/API routes
├── pipeline.py                   # RSS/Substack ingestion, AI CLI prompt flow, LinkedIn staging
├── worker.py                     # Polling worker for scheduled/queued publish records
├── scheduler.py                  # Simple outbox schedule JSON repository
├── publication_planning.py       # Publication plan/target service
├── publication_execution.py      # Due target dispatch, attempts, leases, retry/reconciliation
├── publication_scheduling.py     # Recurrence schedules, campaigns, materialization, execution calendar
├── publication_dispatcher.py     # CLI for execution dispatch/reconciliation
├── publication_scheduler.py      # CLI for schedule preview/materialization/reconciliation
├── plugin_runtime.py             # Application plugin runtime and provider resolver wiring
├── channel_*.py                  # Channel registry, dashboard, actions, storage, models
├── content_*.py                  # Content item/revision storage and services
├── media_*.py                    # Media storage/runtime/library/processing services
├── calendar_view.py              # Dashboard publication calendar view
├── config.json                   # Local runtime configuration with no raw credentials
├── .env.example                  # Example environment variable names only
├── .github/
│   ├── workflows/                # CI/certification workflow definitions
│   └── PULL_REQUEST_TEMPLATE/    # PR template
├── adapters/                     # Legacy adapter namespaces for social platforms
├── assets/                       # Built frontend assets and SVGs
├── frontend/                     # Editor frontend source
├── channels/                     # Built-in channel plugins and placeholders
├── plugins/                      # Providers, sources, transformations, commerce, playbooks
├── integrations/                 # Fixture servers, doctors, and scenario packages
├── src/                          # Core frameworks, plugin SDK/host runtime, providers
├── schemas/                      # JSON schemas for plugin manifests/capabilities
├── templates/                    # Channel plugin and website instrumentation templates
├── tests/                        # Unittest/pytest-compatible phase and feature tests
├── docs/                         # Architecture, runbooks, framework docs, current-state docs
├── scripts/                      # Certification/smoke/helper scripts
├── deploy/                       # Cron/systemd examples
├── desktop/                      # Linux desktop launcher
└── web/instrumentation/          # Browser-side website analytics scripts
```

## Important Subtrees

- `channels/linkedin/`: browser-based LinkedIn channel runtime, workers, target helpers, prompts, metrics, provider state.
- `channels/markdown_website/`: owned publication Markdown renderer, Git publisher, path/media/integrity/verification logic.
- `channels/mastodon/`: API/OAuth PKCE Mastodon client, auth, storage, publish/metrics workers.
- `channels/youtube/`: YouTube channel with OAuth config, publication and upload semantics.
- `src/core/scheduling/` plus `publication_scheduling.py`: internal publication calendar/scheduling contracts and service.
- `src/core/managed_secrets/` and `src/providers/secrets/`: managed secret references, leases, approvals, encrypted/environment providers.
- `src/core/plugin_sandbox/`, `src/core/plugin_host/`, `src/plugin_host_runtime/`: plugin host and sandbox boundaries.
- `src/plugin_sdk/`: public SDK and CLI for plugin workflows.
- `plugins/commerce/woocommerce/`: read-only WooCommerce catalog/outcome adapter.
- `plugins/transformations/video_repurpose/`: media transformation and clip intelligence.
- `integrations/plugin_registry/`: local registry fixtures and TUF-like metadata used by tests.

## Ignored Runtime Areas

```text
.venv/, venv/                    # local virtualenvs
node_modules/                    # local Node dependencies
tmp_media/                       # temporary downloaded/generated media
linkedin_session/                # LinkedIn Playwright browser profile
linkedin_remote_browser/         # remote-debugging browser profile
github_pages_session/            # GitHub Pages Playwright browser profile
studio_data/                     # runtime JSON/SQLite state
outbox/                          # queue, previews, logs, worker state
managed-content/                 # local managed content/runtime output
imports/substack/                # local import cache
*.sqlite, *.sqlite3, *.db, *.log # runtime databases/logs
```
