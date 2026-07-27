# Owned Publication Migrations

Migrations are numbered, checksum-bound, and idempotent. Startup refuses an interrupted or checksum-mismatched owned-publication migration instead of silently running on an incompatible schema.

SQLite remains the project database. Operators should back up the host-owned database before applying future destructive data transformations. Phase 23 adds only forward creation of new tables.
