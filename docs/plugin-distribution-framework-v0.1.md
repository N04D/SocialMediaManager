# Plugin Distribution Framework v0.1

Distribution Framework v0.1 adds wheel-only packaging, release metadata, Sigstore bundle verification, TUF-style registry metadata, quarantine, local versioned installation, disabled-by-default activation, rollback, uninstall, health, integrity, CLI and API surfaces. It does not add a sandbox. Signed is not safe, compatible is not trustworthy, installed is not enabled, and enabled is not official.

## Phase 19 host integration

Activated external plugins are routed through Plugin Host Framework proxies. The main process no longer imports external plugin entrypoints; only the child runtime loads external code after environment and identity checks.
