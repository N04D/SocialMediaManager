# Scheduling Framework Changelog

## v0.1.0

- Added central Scheduling Framework contracts.
- Added publication schedules, recurrence rules, schedule policies, template snapshots, occurrences, exclusions, bounded authorizations, calendar entries, campaigns, campaign members, and campaign coordination policy.
- Added recurrence preview for `once`, `daily`, `weekly`, and `monthly`.
- Added timezone and DST-safe resolution using explicit IANA timezone IDs.
- Added bounded occurrence materialization into existing publication plans and targets.
- Added read-only execution calendar.
- Added campaign grouping, pause, resume, cancellation, and aggregate status.
- Added worker integration so schedule materialization runs before phase-13 dispatch.
- Added scheduling health, integrity, events, audit, API, and compact UI.

Existing Browser, Media, Content, and Execution contract versions are unchanged.
