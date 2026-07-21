# Plugin SDK v1

Plugin SDK v1.0.0 is the stable public boundary for external plugins. It supports channel, provider, and media plugins while keeping Browser, Media, Content, Execution, Scheduling, and Analytics framework contracts unchanged.

Public imports live at `plugin_sdk`. Contributors should not import dashboard, worker, repositories, or concrete built-in channels.

Lifecycle: discovered -> manifest_validated -> compatibility_checked -> dependencies_resolved -> registered -> initialized -> ready/degraded/disabled -> shutdown. Registration must be idempotent and must not open browsers, call remote services, publish, migrate data, or mutate user files.

## Phase 18 distribution

Package releases as pure-Python wheels only. Do not include native extensions, source distributions, bundled SDK copies, production credentials, or runtime dependency installation. Registry browsing and package verification must not import plugin code. Installation is disabled by default; activation is a separate operator decision and requires restart. Signed does not mean safe.
