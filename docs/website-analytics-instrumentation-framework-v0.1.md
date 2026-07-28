# Website Analytics Instrumentation Framework v0.1

Phase 26 adds a provider-neutral instrumentation layer for static websites.
It generates immutable tracking manifests bound to publication snapshots,
opaque page/publication/CTA/conversion IDs, safe page context, static-site
reference templates, and read-only verification evidence.

The backend remains read-only toward analytics providers. It may generate
browser-side reference code and verify public pages, but it does not call
provider event endpoints, install tracking JavaScript into user repositories,
run site builds, deploy hosting, create provider goals, or mutate analytics
accounts.

Readiness is split into `publishing_ready`, `instrumentation_ready`,
`analytics_ready`, and `external_plugin_sandbox_ready`. Phase 20.2 remains
separately blocked and is not changed by this framework.
