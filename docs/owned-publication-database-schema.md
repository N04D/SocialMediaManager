# Owned Publication Database Schema

The phase-23 schema contains durable tables for drafts, revisions, variants, snapshots, publication plans, targets, dependencies, schedules, occurrences, execution events, evidence, reconciliation, integrity, campaigns, funnel observations, attributions, readmodels, and workspace audit events.

All rows carry workspace scope where applicable. JSON columns store schema-validated plain JSON only; pickle, Python object serialization, raw credentials, private keys, cookies, authorization headers, and full article bodies in operational records are forbidden.

Immutable data is corrected by creating a new record that references the older record where needed.
