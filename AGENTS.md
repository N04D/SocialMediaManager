# Repository Guidelines

This repository is the first working layer of `SocialMediaManager`, a Python pipeline that turns Substack posts into social drafts. Keep changes small, local, and easy to extend toward a future review UI.

## Project Structure & Module Organization

- `pipeline.py`: main entry point for RSS ingestion, content processing, AI prompt generation, and LinkedIn staging.
- `dashboard.py`: local dashboard for previewing the current article and queueing schedules.
- The dashboard also has an `Open LinkedIn in new tab` action that opens LinkedIn from the same browser session without popup features.
- The dashboard shows an `Article Launch` status card so background article-draft runs are visible instead of silent.
- The dashboard polls `/launch-status` so launch progress updates appear automatically without manual refreshes.
- The browser-session card includes a direct `Open Al-Batin admin` link for the company page article flow.
- The browser-session card includes an `Open and fill article draft` action button that launches the direct editor in a separate tab, fills the draft, and records launch status.
- The browser-session card also exposes `Article timing` settings so you can set the schedule buffer in minutes.
- Queue detail rows show whether a record follows the `Article -> Al-Batin Page` or `Post -> LinkedIn feed` route.
- Queue tables also show the source publish timestamp so you can verify the 7-day delay for articles.
- Article flow now opens the LinkedIn article editor, fills title/body/cover, and then schedules the post using the article's publish time as the wait-queue target.
- Queue rows are clickable and open a detail view with status, notes, teaser, and worker result.
- Queue filters let you narrow by `queued`, `processing`, `done`, or `failed`, and failed items expose a retry action.
- A `Retry all failed` control resets every failed queue item back to `queued`.
- `worker.py`: polling worker that processes due queue items and stages drafts automatically.
- The dashboard includes a compact worker-run history so you can see recent idle, success, and failure cycles.
- `config.json`: local runtime settings such as RSS URL, browser profile path, and AI CLI command.
- `config.json` can also set `linkedin_remote_debugging_url` to attach Playwright to a Chrome session started with remote debugging.
- `config.json` defaults LinkedIn publishing to the Al-Batin Page in article mode.
- `config.json` includes the Al-Batin company admin URL and Substack archive URL used by the article pipeline.
- `config.json` also includes the direct LinkedIn article editor URL used as the primary article entrypoint.
- `requirements.txt`: Python dependencies for the pipeline.
- `tmp_media/`: temporary downloaded images; delete after each run.
- `linkedin_session/`: persistent Playwright user data directory for LinkedIn login state.
- `outbox/`: local queue, preview cache, and runtime records for scheduled posts.

## Build, Test, and Development Commands

- `python3 -m venv .venv && source .venv/bin/activate`: create and activate a local environment.
- `pip install -r requirements.txt`: install feed parsing, scraping, and browser automation dependencies.
- `playwright install chromium`: install the browser binary used by the pipeline.
- `python pipeline.py --dry-run`: fetch the RSS feed, select the `N-1` article, and print the teaser without opening LinkedIn.
- `python pipeline.py`: run the full staging flow in a browser.
- `python pipeline.py --save-draft`: stage the LinkedIn draft and auto-close after a short pause.
- `python dashboard.py`: start the local dashboard on `http://127.0.0.1:8080`.
- `scripts/start-linkedin-remote-browser.sh`: open a separate Chromium session with remote debugging, starting on the dashboard UI by default.
- `desktop/socialmediamanager-linkedin.desktop`: Linux launcher that opens the dashboard UI browser from the desktop or app menu.
- `deploy/systemd/socialmediamanager-dashboard.service`: systemd unit for keeping the UI online locally.
- `python worker.py --once`: process one due queue item and exit.
- `python worker.py`: keep polling the queue and stage due drafts.
- `deploy/systemd/socialmediamanager-worker.service`: systemd unit for keeping the worker alive.
- `deploy/systemd/socialmediamanager-worker.timer`: systemd timer for periodic queue processing.
- `deploy/cron/socialmediamanager-worker.cron`: cron example for `--once` polling.
- `python -m py_compile pipeline.py`: quick syntax check before sharing changes.

## Coding Style & Naming Conventions

- Use Python 3.12+, 4-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes and dataclasses.
- Keep modules focused on one concern; prefer small helper functions over one large script block.
- Store local-only values in `config.json` and avoid hard-coded secrets or credentials in code.
- Use clear names for artifacts, for example `article_text`, `image_paths`, and `linkedin_user_data_dir`.

## Testing Guidelines

- There is no full automated test suite yet, so prefer reproducible checks.
- Use `--dry-run` for feed parsing and AI prompt validation.
- Use `python -m py_compile pipeline.py` to catch syntax errors quickly.
- If you add tests later, name them `test_*.py` and keep fixtures small and explicit.

## Commit & Pull Request Guidelines

- Git is enabled for this local project. Use `main` as the working branch unless the user asks for a separate branch.
- Before starting edits, run `git status --short` and treat any existing changes as user-owned unless you made them in the current session.
- After meaningful edits, run the relevant checks, then save a local snapshot with a concise Conventional Commit, for example `fix: recover publish queue state`.
- Do not commit browser/session/runtime data. Keep `linkedin_session/`, `linkedin_remote_browser/`, `studio_data/`, `tmp_media/`, `outbox/`, `node_modules/`, virtualenvs, and caches ignored.
- If a crash or interruption happens, recover with this procedure:
  1. Run `git status --short` to see tracked and untracked work.
  2. Run `git diff --stat` and inspect changed files before editing further.
  3. Validate important runtime JSON with `python3 -m json.tool <path>` before deciding whether a save completed.
  4. Check recent runtime records in `studio_data/` and `outbox/` by modification time, but do not commit them.
  5. Resume from the last completed domain step: generated derivative, approval, queued publish job, or worker result.
  6. If the code is intact, run `python3 -m py_compile pipeline.py dashboard.py worker.py channel_actions.py channel_store.py channel_dashboard.py channel_models.py`.
  7. Commit only source, docs, tests, and configuration changes that should be preserved.
- No repository history is available here, so use concise Conventional Commits when you do commit, for example `feat: add rss dry-run`.
- In pull requests, describe the user-visible change, note any config updates, and include screenshots or a short screen recording for browser-flow changes.
- Call out any manual steps needed to validate LinkedIn automation, because browser selectors and platform behavior can change.

## Security & Configuration Tips

- Do not commit `linkedin_session/`, `tmp_media/`, or personal credentials.
- Keep the LinkedIn profile directory local so repeated runs reuse the same authenticated session.
- If you want Playwright to use an already-open browser, start Chrome with remote debugging and set `linkedin_remote_debugging_url` in `config.json`.
- The dashboard also exposes a browser-session form so you can switch between attach mode and the local persistent profile.
- The desktop launcher starts on the dashboard first; from there you can open LinkedIn manually in the same browser session.
- Articles are prioritized over posts, and the article flow fills the teaser in LinkedIn's "Tell your network" box before placing the original Substack HTML, title, and cover image. It then schedules the post using a short buffer window instead of publishing immediately.
- The article flow uses the direct LinkedIn article editor URL first, then falls back to the company admin route only if needed.
- Replace the placeholder path in the cron example before using it, and keep service files pointed at your local clone.
- If you want the UI continuously available on this machine, install the dashboard systemd service alongside the worker service.
- Enable the UI with `systemctl --user enable --now socialmediamanager-dashboard.service` after copying the unit to `~/.config/systemd/user/`.
