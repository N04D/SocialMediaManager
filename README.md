# SocialMediaManager

Phase 22 adds an Owned Publication Workspace for website-first funnels: compose a full Markdown article, create an immutable revision, preview Markdown Website output, plan website plus LinkedIn/Mastodon targets, verify the website before social distribution, reconcile uncertain states without blind retries, and inspect content-aware funnel metrics.

The workspace does not build or host a website. Git push is distinct from public URL verification, and phase 20.2 Linux sandbox certification remains separately blocked until a supported Linux host proves `linux_production_ready=true`.

Phase 23 persists owned-publication drafts, immutable revisions, variants, publication plans, evidence, reconciliation leases, campaigns, and funnel readmodels in a host-owned SQLite store.

Phase 24 adds production operations for the owned-publication stack: browser/worker CI certification, fail-on-skip release gates, worker supervision, storage health, managed SQLite backups, staged restore validation, support bundles, and a release-check command. External plugin sandbox certification from phase 20.2 remains separately blocked and is reported separately.

Phase 25 adds a read-only website analytics provider framework and first-party Plausible adapter. It stores only secret references, uses host-owned origins and HTTP facades, syncs provider observations into content-aware funnel readmodels, and keeps publishing readiness independent from analytics provider outages.

Phase 26 adds provider-neutral website instrumentation: snapshot-bound manifests, opaque tracking IDs, safe static-site templates, a dependency-free browser runtime, and a Plausible browser bridge. The backend still does not send analytics events; browser-side events only run after a website operator manually installs the reference integration.

Phase 27 adds staging analytics certification. Required certification is deterministic and fixture-only; optional provider staging smoke is explicitly opt-in and reports `staging_provider_certification_not_run` when no safe staging configuration exists.

Phase 28 adds certification evidence trust: canonical packages, provenance,
optional signer verification, managed import/export, replay prevention,
freshness policies and operator review. A configured CI workflow remains
`artifact_not_imported` until a real evidence artifact is imported and verified.

Phase 29 adds trusted signer enrollment and a read-only GitHub Actions artifact
importer. Workflow success is not enough: exact repository, workflow, run
attempt, commit, artifact ID, provider digest, internal package checksums,
attestation, freshness, trust policy and operator review are checked separately.
Private keys remain secret references only.

Phase 30 adds managed secrets and operator trust controls. Local host signer
keys can be generated directly into an encrypted host-owned vault, GitHub
read-only credentials can be registered as managed secret references, and all
secret consumption uses purpose-bound call-scoped leases. Remote CI remains
`artifact_not_imported` and real GitHub import remains
`real_github_import_not_run` until an operator performs a concrete import.

Phase 31 adds the GitHub CI evidence operator flow. Operators can onboard a
managed GitHub credential, validate a registered origin, discover runs for an
exact commit, select a concrete run attempt and artifact ID, dry-run metadata,
execute a durable import, review evidence, and promote it only for that exact
commit. The flow does not start GitHub Actions and keeps remote CI at
`artifact_not_imported` until a concrete artifact is imported, verified,
reviewed, and promoted.

SocialMediaManager turns long-form content into channel-specific publication targets.

## Markdown Website Channel

`channel.markdown_website` is the built-in owned-publication endpoint for full Markdown articles. It writes deterministic Markdown and media into an allowlisted Git worktree, commits exact mutation paths, optionally pushes to an allowlisted branch, verifies the public URL, and only then unlocks dependent LinkedIn or Mastodon distribution targets.


## Alpha onboarding

Phase 32 adds `plugin-sdk onboarding start` and `plugin-sdk onboarding demo-start` for a resumable alpha first-publication setup. Alpha-ready is not production-ready; analytics and social channels are optional, publication requires explicit confirmation, and deterministic demo mode uses only synthetic temporary resources.

## Current Snapshot Guide

For a concise description of the current implementation, read:

- `docs/CURRENT_SYSTEM_STATE.md`
- `docs/ARCHITECTURE_CURRENT.md`
- `docs/REPOSITORY_MAP.md`

## Requirements

- Python 3.12+
- Node.js and npm for the editor bundle
- Chromium/Playwright browser dependencies for browser-backed flows
- Git for Markdown Website publishing
- Optional local tools for specific plugins, such as ffmpeg/media tooling and local transcription model files

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
npm install
playwright install chromium
```

## Configure

Runtime configuration is primarily in `config.json`. Keep machine-local credentials and browser/session state out of Git.

Use `.env.example` as a list of optional local environment variables. The application also contains a managed-secret framework; production-like credentials should be stored as secret references rather than committed values.

Important local-only paths are ignored by Git:

- `linkedin_session/`
- `linkedin_remote_browser/`
- `github_pages_session/`
- `studio_data/`
- `outbox/`
- `tmp_media/`
- virtualenvs, caches, logs, and local databases

## Run

Dashboard:

```bash
python dashboard.py --host 127.0.0.1 --port 8080
```

RSS/Substack to LinkedIn dry run:

```bash
python pipeline.py --dry-run
```

Full pipeline/staging flow:

```bash
python pipeline.py
```

Queue worker once:

```bash
python worker.py --once
```

Continuous queue worker:

```bash
python worker.py
```

Publication execution dispatcher:

```bash
python publication_dispatcher.py health
python publication_dispatcher.py due --dry-run
python publication_dispatcher.py run-once --dry-run
```

Publication scheduler:

```bash
python publication_scheduler.py health
python publication_scheduler.py preview --starts-at-local 2026-08-10T09:00:00 --timezone Europe/Amsterdam
python publication_scheduler.py materialize --dry-run
```

Plugin SDK CLI examples:

```bash
python -m src.plugin_sdk.cli --help
python -m src.plugin_sdk.cli markdown-website profiles
python -m src.plugin_sdk.cli secrets list
```

Frontend bundle:

```bash
npm run build
```

## Development

- Keep local state in ignored runtime directories.
- Prefer small, focused changes.
- Do not commit browser profiles, session cookies, logs, local SQLite databases, `node_modules/`, virtualenvs, or provider tokens.
- Use managed secret references for provider credentials where supported.

## Tests and Checks

Typical local checks:

```bash
python -m compileall .
python -m pytest -q
ruff check .
ruff format --check .
npm run build
```

The full suite is large and includes browser-dependent tests. If Playwright-managed Chromium or local browser binaries are missing, browser tests may skip or fail depending on the test.

For a narrower smoke check:

```bash
python -m py_compile pipeline.py dashboard.py worker.py channel_actions.py channel_store.py channel_dashboard.py channel_models.py
python worker.py --once
npm run build
```
