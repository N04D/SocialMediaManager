# Owned Publication Browser Tests

Phase 23 adds a project-conformant browser-style HTTP test against the real dashboard server and a temporary SQLite database. It creates and autosaves an article, reloads through API routes, verifies concurrency conflict handling, restarts the server, and confirms durable state remains.

The test uses a temporary content directory and deterministic services. It does not use production credentials, production social accounts, external network calls, or the repository `content/` and `drafts/` directories.
