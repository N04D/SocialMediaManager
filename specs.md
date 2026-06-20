# SocialMediaManager Specs

## Goal

Build a local-first Python manager that turns Substack RSS posts into social drafts with a one-article delay. The initial channel is LinkedIn; later adapters can target Instagram, TikTok, X, and other formats.

## MVP Flow

1. Read the Substack RSS feed from `config.json`.
2. Skip the newest item and select the previous post (`N-1`).
3. Extract article title, link, HTML, text, and embedded images.
4. Download images into `tmp_media/` for temporary staging.
5. Send title and article text to a local AI CLI for a LinkedIn teaser.
6. Open LinkedIn with a persistent Playwright profile, or attach to an existing Chrome session when `linkedin_remote_debugging_url` is set, and stage the draft or article for the Al-Batin Page.
7. Remove temporary media after the run.

## Front Layer

- `dashboard.py` shows the latest delayed article, a generated teaser, and the current schedule queue.
- A simple form stores planned posts in `outbox/scheduled_posts.json`.
- A browser-session control lets you save a remote debugging URL for attaching to an already logged-in Chromium session, or fall back to the local persistent profile.
- The LinkedIn target defaults to the Al-Batin Page admin dashboard in article mode, so scheduled runs generate a company-page article draft from the Substack source.
- Article timing is configured independently from the source date. Use `linkedin_article_schedule_buffer_minutes` to schedule the article a short time in the future.
- The dashboard shows a live article-launch status card so you can see whether the draft flow is starting, running, done, or failed.
- The launch card auto-polls `/launch-status`, so you do not need to refresh the page manually to see progress.
- The browser-session card exposes a direct `Open Al-Batin admin` link, and queue details label each item as `Article -> Al-Batin Page` or `Post -> LinkedIn feed`.
- The browser-session card also exposes the direct LinkedIn article editor URL, which is the primary article entrypoint.
- The browser-session card includes an `Open and fill article draft` action that launches the editor in a separate tab, fills the title/body/cover, and records launch status.
- Queue tables still show the source publish timestamp for reference, but article timing no longer uses the original Substack date.
- The article draft flow fills the teaser in the LinkedIn "Tell your network" box, then places the original Substack article HTML into the LinkedIn body, plus title and cover image for the Al-Batin Page, and finally schedules the post for the computed publish time.
- Clicking a queue row opens a detail view with status, timing, notes, teaser, media sources, and the last worker result.
- Queue filters let you switch between `all`, `queued`, `processing`, `done`, and `failed`.
- Failed items include a retry button that resets the record back to `queued`.
- A `Retry all failed` control resets every failed record in one pass.
- A second action launches the LinkedIn draft flow in the background with draft auto-save enabled.
- The dashboard has an `Open LinkedIn in new tab` action that reuses the configured browser session and opens LinkedIn from the UI before you stage a draft.

## Queue Worker

- `worker.py` polls for due queue items and stages them when `scheduled_for` is reached.
- It re-downloads any saved `image_sources` into `tmp_media/` before opening LinkedIn.
- On success or failure, it updates the queue record so the dashboard shows the latest state.
- The dashboard keeps a compact history of recent worker runs, including idle loops.

## Deployment

- `deploy/systemd/socialmediamanager-dashboard.service` keeps the dashboard reachable on `127.0.0.1:8080`.
- The local install path is `~/.config/systemd/user/socialmediamanager-dashboard.service`, enabled with `systemctl --user enable --now socialmediamanager-dashboard.service`.
- `scripts/start-linkedin-remote-browser.sh` starts a dedicated Chromium session with remote debugging enabled for attach mode and opens the dashboard first.
- `desktop/socialmediamanager-linkedin.desktop` provides a clickable launcher for the same browser session, with a custom icon.
- `deploy/systemd/socialmediamanager-worker.service` keeps the queue worker alive with automatic restart.
- `deploy/systemd/socialmediamanager-worker.timer` runs the worker periodically even if you prefer short polling windows.
- `deploy/cron/socialmediamanager-worker.cron` is a simple fallback for machines where systemd user units are not convenient.

## Future Shape

- `ingest`: feed parsing and article normalization.
- `content_engine`: channel-specific copy generation.
- `asset_engine`: image and video preparation.
- `channel_adapters`: LinkedIn first, then Instagram, TikTok, and X.
- `review_ui`: a web front for inspection, edits, and scheduling.
