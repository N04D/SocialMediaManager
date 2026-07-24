# Example

Generated api-first channel plugin using Plugin SDK v1.

## Phase 18 distribution

Package releases as pure-Python wheels only. Do not include native extensions, source distributions, bundled SDK copies, production credentials, or runtime dependency installation. Registry browsing and package verification must not import plugin code. Installation is disabled by default; activation is a separate operator decision and requires restart. Signed does not mean safe.

## Phase 20 sandboxing

External community plugins run through the Plugin Host OS sandbox before their entrypoint is imported. Direct sockets, broad filesystem access, subprocesses, repository paths, `content/`, `drafts/`, and home credentials are not available. Use broker callbacks and SDK facades instead. Development override is local-only, degraded, and not release-ready.
