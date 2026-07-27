# Owned Publication Production Operations v0.1

Phase 24 makes the owned-publication stack operationally releasable while preserving the phase-23 architecture:

```text
application services -> durable repositories -> host-owned worker supervisor -> API/UI/CLI
```

Workers call existing repository and application service methods. Plugins, MCP, and UI code do not access the database directly.

## Release Gates

CI defines:

- `Owned Publication Browser and Worker Certification`
- `Owned Publication Release Gate`

The certification job runs `scripts/owned-publication-certify.py`, which fails when required phase-23.1 browser or worker suites skip. Repository-wide skips outside that scoped gate remain allowed.

## Operations Scope

Phase 24 covers worker supervision, storage health, backups, restore validation, retention previews, support bundles, health/readiness endpoints, operations metrics, disaster-recovery tests, and release readiness.

Phase 20.2 remains separate. Owned-publication operations can be ready while `external_plugin_sandbox_ready=false`.
