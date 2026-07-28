# Staging Analytics Certification Framework v0.1

Phase 27 adds opt-in staging analytics certification for synthetic pages. The
required path is deterministic: a local synthetic staging page, real Chromium,
the phase-26 browser runtime, a fake provider endpoint, phase-25 sync fixtures,
immutable observations, provider-observed reconciliation, and a safe report.

The optional staging provider smoke is not required in pull requests. It may run
only with explicit operator input and host-owned staging references. Missing
staging configuration is reported as `staging_provider_certification_not_run`,
not as a live pass.

The backend remains read-only toward analytics providers. It does not call
Plausible Events API, create goals, mutate sites, delete provider data, or retry
browser events after uncertainty.
