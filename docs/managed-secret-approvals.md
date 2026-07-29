# Managed Secret Approvals

Approvals are bound to action, resource ID, resource version, fingerprint, actor, and timestamp. Changing the resource invalidates prior approval.

Four-eyes approval defaults to `self_approval_allowed = false` for:

- production signer activation;
- GitHub credential approval;
- active signer rotation;
- signer revocation;
- backend changes.

Approval cannot make an unhealthy or revoked secret usable.
