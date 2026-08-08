# Current System State

This document records what is present in the repository at the time of the snapshot. It is descriptive only; it does not describe planned future work.

## Core

- Application entrypoints:
  - `dashboard.py`: local HTTP dashboard using `ThreadingHTTPServer` and `BaseHTTPRequestHandler`.
  - `pipeline.py`: Substack/RSS ingestion, article processing, AI prompt execution, LinkedIn browser staging, and legacy article flow helpers.
  - `worker.py`: polling worker for queued social publishing jobs.
  - `publication_dispatcher.py`: CLI for dispatching due publication targets through the execution service.
  - `publication_scheduler.py`: CLI for recurrence preview, schedule materialization, reconciliation, and health.
  - `src/plugin_sdk/cli.py`: `plugin-sdk` CLI covering plugin scaffolding, validation, packaging, registry, host, sandbox, onboarding, Markdown Website, owned publication, analytics, certification, secrets, and instrumentation commands.
- Backend:
  - Primarily Python modules with JSON-file repositories and selected SQLite services.
  - Dashboard routes expose channel state, publishing, content editor, setup/onboarding, managed secrets, certification, execution calendar, and configuration screens.
- Frontend:
  - Server-rendered dashboard HTML/CSS in `dashboard.py`.
  - Rich editor app source in `frontend/editor-app.js`; bundled output in `assets/editor-app.js`.
  - Calendar UI in `calendar_view.py`.
- Datastore:
  - `studio_data/` JSON files and `studio_data/owned_publication.sqlite` are local runtime state and are ignored.
  - `outbox/` queue/preview/log state is local runtime state and ignored.
  - `content/drafts/` contains repository-tracked draft fixtures/content plus local draft changes.
  - `channel_storage.py` and `channel_store.py` provide locked JSON stores.
  - `src/core/owned_publication/persistence.py`, managed secret persistence, analytics persistence, and certification persistence provide SQLite-backed repositories.
- Scheduler/workers:
  - `scheduler.py` stores simple outbox schedule records.
  - `publication_scheduling.py` implements publication schedules, recurrence rules, policies, occurrences, exclusions, authorizations, campaigns, materialization, and execution calendar projection.
  - `worker.py` handles due outbox queue records and stages LinkedIn/browser jobs.
  - `publication_execution.py` manages due targets, execution attempts, leases, retry decisions, uncertain states, and reconciliation.
- Event/task processing:
  - JSON event/audit stores exist for channel state, execution, scheduling, analytics, managed secrets, browser pilots, and plugin sandbox/host workflows.
  - Execution and scheduling layers use explicit statuses and lease/reconciliation records rather than blind retries.
- Configuration:
  - `config.json` is the local runtime config for RSS, LinkedIn/browser settings, content directories, feature flags, and channel options.
  - `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `package.json`, and `package-lock.json` define tooling/dependencies.
- Secrets/config handling:
  - Managed secret abstractions live under `src/core/managed_secrets/` with environment and local encrypted providers under `src/providers/secrets/`.
  - Channel/provider records store secret references instead of raw token values where implemented.
  - Browser profiles, session cookies, vault/runtime state, and logs are ignored by `.gitignore`.

## Plugins / Integrations

| Plugin/integration | Purpose | Input capabilities | Output capabilities | Auth | Status | Key files | Tests | Known limits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `channels/linkedin` | LinkedIn post generation, preview, browser publish, metrics snapshots | Approved content variants, media, browser session | LinkedIn post draft/publish evidence, metrics snapshots | Local Playwright profile or remote debugging browser | IMPLEMENTED/PARTIAL | `channels/linkedin/*`, `pipeline.py`, `worker.py` | `tests/test_linkedin_*`, channel tests | Browser selectors/session state can drift; article flow remains legacy/manual-adjacent. |
| `channels/markdown_website` | Owned Markdown website publication | Content snapshots, media assets, repository reference | Markdown files, Git commit/push evidence, verification status, metrics binding | Git worktree plus optional secret references | IMPLEMENTED | `channels/markdown_website/*`, `docs/markdown-website-*` | `tests/test_markdown_website_channel_phase21.py` and publication tests | Does not build arbitrary site commands; public URL verification is separate from Git push. |
| `channels/mastodon` | API-first Mastodon text/image publishing and metrics | Approved status variants, media | Mastodon status/media evidence and metrics | OAuth PKCE, token refs in local secret store | IMPLEMENTED/PILOT | `channels/mastodon/*` | `tests/test_mastodon_channel_phase16.py` | Requires instance/account configuration; network smoke is fixture-oriented unless configured. |
| `channels/youtube` | YouTube video/Short publishing channel | Short-video assets, metadata/captions, execution plan | YouTube upload evidence and status | OAuth/refresh token secret refs | IMPLEMENTED/PARTIAL | `channels/youtube/*`, `scripts/smoke-youtube-short-upload.py` | `tests/test_phase40_youtube_*` | Real uploads require explicit `YOUTUBE_ACCESS_TOKEN`/managed secrets and confirmation. |
| `channels/instagram`, `channels/x`, `channels/substack`, `channels/blog` | Placeholder channel entries | None beyond manifest metadata | None | None | SCAFFOLD | `channels/*/channel.manifest.json`, README files | Registry tests | No live publishing implementation. |
| `plugins/providers/legacy_browser` | Existing local Playwright browser provider | Browser session requests | Browser actions/session state | Local profile/Playwright | IMPLEMENTED | `plugins/providers/legacy_browser/*` | Browser/provider tests | Browser UI dependent. |
| `plugins/providers/auto_browser` | Remote/managed browser provider abstraction | Browser session requests, uploads | Browser provider sessions/artifacts | Bearer token env reference | PARTIAL/IMPLEMENTED | `plugins/providers/auto_browser/*`, `integrations/auto-browser/*` | `tests/test_auto_browser_*` | Requires external Auto Browser service for real operation. |
| `plugins/providers/local_media_storage` | Local media storage provider | Media blobs/references | Stored media assets | Local filesystem | IMPLEMENTED | `plugins/providers/local_media_storage/*`, media services | Media framework tests | Runtime media data ignored. |
| `plugins/providers/local_transcription` | Local transcription provider | Audio/video media | Transcript text/timeline | Local model/runtime | IMPLEMENTED/PARTIAL | `plugins/providers/local_transcription/*`, `scripts/smoke-local-transcription.py` | Phase 37 tests | Real transcription depends on local model/dependencies. |
| `plugins/sources/youtube` | YouTube source ingest/plugin | YouTube source references | Source content/media metadata | Config/HTTP as implemented | PARTIAL | `plugins/sources/youtube/*` | Phase 35/40 tests | Real network behavior is opt-in. |
| `plugins/transformations/video_repurpose` | Long-video to short-video transformation | Video media/transcripts | Short assets, clips, captions | Local processing tools | IMPLEMENTED/PARTIAL | `plugins/transformations/video_repurpose/*` | Phase 36/38 tests | Requires local media tooling for real rendering. |
| `plugins/transformations/transcript_clip_candidates` | Transcript clip candidate manifest | Transcript input | Candidate metadata | None | SCAFFOLD | manifest only | Phase tests | No substantial implementation file. |
| `plugins/commerce/catalog` | Fixture commerce catalog | Catalog fixture data | Product records/outcomes | None | IMPLEMENTED fixture | `plugins/commerce/catalog/*` | Phase 35 tests | Fixture catalog. |
| `plugins/commerce/woocommerce` | WooCommerce read-only catalog/outcome adapter | WooCommerce API responses | Products/orders/outcome mappings | Managed secret refs for consumer key/secret | IMPLEMENTED/PARTIAL | `plugins/commerce/woocommerce/*` | Phase 39 tests | Read-only; real credentials/config required. |
| `plugins/playbooks/creator_commerce` | Creator commerce playbook | Content, products, attribution | Recommendations/playbook output | None direct | IMPLEMENTED/PARTIAL | `plugins/playbooks/creator_commerce/playbook.py` | Phase 35/39 tests | Depends on catalog/outcome inputs. |
| `integrations/*` | Fixture/doctor/scenario packages | Local fixtures | Doctor reports/scenario data | Mostly none or fake secrets | IMPLEMENTED fixtures | `integrations/*` | Many phase tests | Most are deterministic test integrations, not production external connections. |

## Social

- LinkedIn:
  - Generates LinkedIn post prompts from content.
  - Supports connect/session check, dry-run/publish job flow, local Playwright profile, remote debugging URL, metrics snapshot refresh, and worker locking.
  - Legacy `pipeline.py` also handles Substack-to-LinkedIn article staging and Al-Batin page article flow.
- Mastodon:
  - API-first OAuth PKCE flow, app registration, status/media publishing, metrics, disconnect/revoke semantics, SSRF controls.
- YouTube:
  - Channel plugin supports connect/status/health and video/Short publication planning, OAuth config/secret refs, metadata/provenance, resumable upload semantics in tests.
- Instagram/X/Substack/Blog:
  - Present as placeholder/scaffold manifests and README entries only.

## Website

- Markdown Website channel renders immutable content snapshots to deterministic Markdown and media paths.
- Git integration is implemented through `channels/markdown_website/git_publisher.py`; it stages exact mutation manifest paths, commits, optionally pushes, and records evidence.
- Verification checks public URLs separately from Git push through `channels/markdown_website/verification.py`.
- Website analytics and instrumentation are separate frameworks:
  - `src/core/website_analytics/*` with Plausible provider under `src/providers/analytics/plausible/*`.
  - `src/core/website_instrumentation/*` with generated static-site manifests/templates and browser-side runtime files in `web/instrumentation/`.
- GitHub Pages helper:
  - `scripts/configure_github_pages.py` is a Playwright utility for `N04D/website` Pages settings and custom domain setup. It is not part of the core publishing service.
- Website doctor/readiness:
  - Markdown Website doctor/integrity/verification commands exist in `src/plugin_sdk/cli.py` and `integrations/markdown_website/doctor.py`.
  - Alpha readiness separates local alpha readiness from production/CI readiness.

## Agenda / Calendar

- `calendar_view.py` renders a visual publication calendar from:
  - outbox schedule records loaded through `scheduler.load_schedule()`;
  - content drafts loaded through `content_store.list_content_items()`.
- Dashboard route `/calendar` displays this UI.
- `dashboard.py` also exposes an execution/content calendar:
  - route `/content-calendar`;
  - API `/api/execution-calendar`;
  - schedule actions under `/content-calendar/create-schedule`, `/materialize`, `/pause`, `/resume`, `/cancel`;
  - campaign actions under `/content-calendar/create-campaign`, `/add-campaign-member`, `/campaign-pause`, `/campaign-resume`, `/campaign-cancel`.
- Providers:
  - No external Google Calendar, CalDAV, Microsoft Graph, or calendar provider is implemented in repository code.
- Event operations:
  - The current calendar reads and projects internal publication schedules/events.
  - It creates/modifies/cancels internal publication schedules and campaigns.
  - It does not create, update, delete, or free/busy-query external calendar events.
- Availability/free-busy:
  - Not implemented for external calendars.
- Scheduler integration:
  - `publication_scheduling.py` materializes recurrence rules into occurrences and links them to publication plans/targets.
  - `publication_execution.py` dispatches due targets using leases and retry/reconciliation policy.
- Auth:
  - Internal calendar operations use local dashboard access only; no external calendar OAuth exists.
- Tests:
  - `tests/test_scheduling_framework_phase14.py`, `tests/test_campaign_workspace_phase23.py`, and execution/calendar tests cover internal scheduling behavior.
- Current limitations:
  - Internal publication calendar only; no provider sync.
  - Runtime schedule state lives in ignored `studio_data/` and `outbox/`.

## AI

- `pipeline.py` has AI CLI integration:
  - `ai_cli_command`, `ai_cli_args`, `ai_cli_mode` in `config.json`;
  - prompt generation for Substack/article-to-social teaser generation.
- Channel prompts:
  - `channels/linkedin/prompts/linkedin-post.md` and `channels/linkedin/rules.yaml`.
  - Dashboard supports editing an AI prompt template for channel plugin generation.
- Agent/content graph:
  - `src/core/content/agentic_graph.py`, `docs/agentic-content-graph-v0.1.md`, and playbook/commerce/video plugins provide agentic composition concepts.
- Transformations:
  - Video repurpose and clip intelligence plugins perform deterministic/local transformations and ranking signals.
- RAG/research:
  - No dedicated RAG index, vector store, web research subsystem, or retrieval pipeline was found.
- LLM providers:
  - No direct OpenAI SDK integration was found; AI execution is delegated through CLI configuration.

## Security and Runtime Data Audit

- Ignored local runtime/security-sensitive paths include `.venv/`, `venv/`, `node_modules/`, `tmp_media/`, `linkedin_session/`, `linkedin_remote_browser/`, `github_pages_session/`, `studio_data/`, `outbox/`, `.env*`, databases, and logs.
- Local browser cookie/login data was found only in ignored browser profile directories.
- Local SQLite runtime database was found at `studio_data/owned_publication.sqlite` and is ignored.
- `content/drafts/` contains tracked and untracked user/content fixtures; these are not browser/session secrets, but they may contain authored content and should be reviewed before publishing broadly.
