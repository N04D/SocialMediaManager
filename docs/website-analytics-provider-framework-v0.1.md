# Website Analytics Provider Framework v0.1

The website analytics layer is provider-neutral and read-only. It stores
provider accounts, event mappings, sync states, cursors, rate limits,
attribution records, and quality reports in the owned-publication SQLite
database. Metric observations are ingested through the existing durable funnel
observation path and remain immutable.

Public APIs accept only host-owned `origin_reference_id` values and
`secret_reference_id` values. They do not accept raw provider URLs, raw API
keys, arbitrary query bodies, sockets, SQL, or filesystem paths.

Publishing readiness is independent from analytics availability. Analytics
outages set `analytics_degraded` and keep `publishing_ready=true` unless another
publishing subsystem is unhealthy. Phase 20.2 external plugin sandbox readiness
remains separately reported as blocked on this host.

Phase 26 instrumentation supplies the page context and event properties that the
collector later sees through provider observations. The provider framework
continues to be read-only: it collects Stats API data and never emits browser
events or mutates provider configuration.
