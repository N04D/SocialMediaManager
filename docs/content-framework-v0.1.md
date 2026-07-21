# Content Framework v0.1

Content Framework v0.1 introduces a provider-independent content domain above the existing browser, channel, and media layers.

## Contracts

- `CONTENT_FRAMEWORK_VERSION = "0.1.0"`
- `CONTENT_ITEM_CONTRACT_VERSION = "1.0"`
- `CONTENT_REVISION_CONTRACT_VERSION = "1.0"`
- `CHANNEL_CONTENT_VARIANT_CONTRACT_VERSION = "1.0"`
- `CONTENT_REQUIREMENTS_CONTRACT_VERSION = "1.0"`
- `PUBLICATION_PLAN_CONTRACT_VERSION = "1.0"`
- `PUBLICATION_TARGET_CONTRACT_VERSION = "1.0"`

Browser Framework v1 and Media Framework v0.3 contract versions are unchanged.

## Services

- `ContentService` manages canonical content items, immutable revisions, channel variants, requirements, validation, and lazy compatibility migration.
- `PublicationPlanningService` manages publication plans, targets, immutable snapshots, stale detection, and queueing into the existing publish job infrastructure.
- Channels register requirements but do not own canonical content storage.

## Current Limits

The framework does not generate, rewrite, translate, shorten, score, or schedule content automatically. Queueing creates existing publish jobs; browser execution remains in channel workers.

