# Owned Publication Persistence v0.1

Phase 23 makes the owned-publication workspace database-backed. Drafts are mutable and require `expected_version`; revisions, variants, snapshots, execution events, and evidence are append-only or immutable.

Production uses a host-owned SQLite database with foreign keys, WAL, schema migrations, idempotency records, audit events, and rebuildable readmodels. The database never uses `content/` or `drafts/` as fixtures.

Phase 20.2 remains separately blocked: Linux sandbox certification is not marked production-ready by this phase.
