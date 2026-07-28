# Certification Evidence Operator Control

Operators can list, inspect, verify, compare, review and revoke evidence.

Review decisions are `approved`, `rejected`, `needs_follow_up`, and
`acknowledged_stale`. Review does not change technical validity. Invalid
evidence cannot be made valid by approval.

Staging run start is controlled:

1. Dry-run validates profile, origin, staging account, mappings, worker health
   and active-run status.
2. Dry-run opens no browser and sends no event.
3. Execute requires explicit confirmation and creates a new immutable run.
