# Analytics Framework v0.1

Phase 15 introduces a channel-independent analytics domain for publication-level performance.

## Scope

Analytics v0.1 stores immutable metric observations, links them to immutable publication attribution, and builds rebuildable readmodels for publications, content, revisions, variants, media, campaigns, channels, and accounts.

The framework does not generate recommendations, infer causality, scrape audience identities, or open browser sessions. Channel runtimes collect platform metrics and hand normalized inputs to `AnalyticsIngestionService`.

## Contracts

- `ANALYTICS_FRAMEWORK_VERSION = "0.1.0"`
- `METRIC_DEFINITION_CONTRACT_VERSION = "1.0"`
- `METRIC_OBSERVATION_CONTRACT_VERSION = "1.0"`
- `PUBLICATION_ATTRIBUTION_CONTRACT_VERSION = "1.0"`
- `DERIVED_METRIC_CONTRACT_VERSION = "1.0"`
- `ANALYTICS_READ_MODEL_CONTRACT_VERSION = "1.0"`
- `ANALYTICS_INGESTION_CONTRACT_VERSION = "1.0"`

Browser, Media, Content, Execution, and Scheduling contract versions are unchanged.

## Services

- `MetricDefinitionRegistry`
- `PublicationAttributionService`
- `AnalyticsIngestionService`
- `AnalyticsReadModelService`
- `AnalyticsIntegrityService`

All services are registered through `ApplicationPluginRuntime` as `analytics.service`.
