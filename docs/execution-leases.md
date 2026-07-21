# Execution Leases

`ExecutionLease` provides exclusive target claims.

Fields:

- `id`
- `target_id`
- `attempt_id`
- `worker_id`
- `claimed_at`
- `heartbeat_at`
- `expires_at`
- `released_at`
- `status`
- `version`

Only one active, unexpired lease may exist per target. Heartbeats renew expiry and increment the version. Expired leases are recovered through reconciliation rather than assumed safe.

Worker IDs are opaque process-local identifiers and are not intended as public metrics labels.

