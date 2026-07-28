# Staging Analytics Runbook

1. Configure a host-owned staging origin with `environment=staging` and
   `synthetic_only=true`.
2. Use a staging analytics account marked synthetic-test allowed.
3. Register the synthetic page profile, which requires `noindex,nofollow` and
   `smm-synthetic-analytics-page=true`.
4. Create a new certification run. Each run receives a new opaque
   `smm_synthetic_run_id`.
5. Execute browser certification only with explicit opt-in.
6. Reconcile provider observations through phase-25 read-only sync.

If the browser phase becomes uncertain after a click starts, do not click again.
Run provider reconciliation first and create a new run only after an explicit
operator decision.
