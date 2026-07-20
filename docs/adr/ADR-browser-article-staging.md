# ADR: Browser Framework Boundary For Article And Staging Flows

Status: accepted for Browser Framework v1.0.0.

## Context

`pipeline.py` still contains legacy/manual browser tooling for LinkedIn article and staging workflows. The channel plugin framework now owns active LinkedIn channel operations: connect, session check, publish, metrics, and scraping. Article publishing is not migrated in phase 8.

## Decision Matrix

| Flow | Dashboard | Worker | Uses LinkedIn auth | Publishes LinkedIn | Tested | Risk | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Active article publishing to Al-Batin Page | yes | manual/queued | yes | yes | limited | can bypass provider locking | migrate_in_future |
| Experimental browser staging helpers | manual | no | sometimes | no/unclear | limited | can confuse provider state | manual_legacy_deprecated |
| Generic local content preparation | yes | yes | no | no | normal app checks | outside channel boundary | manual_legacy_supported |
| Dead selector experiments | no | no | unclear | no | no | maintenance drag | remove |

## Consequences

- Article publishing is not advertised as a Browser Framework v1 channel capability.
- Legacy/manual article flows must not run for accounts explicitly configured for Auto Browser.
- Legacy/manual flows must not update provider-bound authentication state.
- LinkedInChannelRuntime does not import pipeline article helpers.
- Migration or removal is deferred to a future phase with dedicated tests.

## Deprecation Metadata

Legacy/manual article staging:

- deprecated: true;
- deprecated_since: `browser-framework-v1.0.0`;
- replacement: `LinkedInChannelRuntime` article capability in a future version;
- removal_target: `phase 10` or a dedicated article migration;
- reason: legacy flow can bypass provider-managed browser ownership.
