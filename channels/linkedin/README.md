# LinkedIn Plugin

This plugin is the first fully wired channel plugin for the local studio MVP.

What it currently does:

- Discovers through `channel.manifest.json`.
- Generates a `linkedin_post` derivative from a canonical Markdown document.
- Requires explicit review and approval before publish-job creation.
- Uses a local persistent Playwright profile for connect, session checks, publish,
  and metrics collection.
- Stores publish jobs, metric jobs, snapshots, logs, and screenshots locally in
  `studio_data/` and `outbox/channel_screenshots/`.

Local browser profile:

- Reuses the project profile path from `config.json` via `linkedin_user_data_dir`.
- Defaults to headed mode for connect and debug-friendly flows.
- Never stores passwords or exported cookie dumps in application state.

Known limitations in this MVP:

- Metrics extraction is best-effort and relies on visible post-level numbers from
  the authenticated user's own LinkedIn post view.
- Live publish confirmation and post URL capture should be verified locally
  against the current LinkedIn UI before relying on it for production posting.

