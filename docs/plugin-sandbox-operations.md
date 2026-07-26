# Sandbox Operations

Operators can inspect sandbox status through `/api/plugin-sandbox/health`, `/api/plugin-sandbox/platform`, `/api/plugin-sandbox/policies`, `/api/plugin-sandbox/plans`, `/api/plugin-sandbox/attestations`, `/api/plugin-sandbox/violations`, `/api/plugin-sandbox/integrity`, and `plugin-sdk sandbox ...`.

Development override is local-only, explicit, audited, and permanently marked as degraded. It never changes a plugin into official or trusted status.

Doctor interpretation:

- `configured`: the policy requires the control.
- `detected`: the kernel or library appears available.
- `enforced`: the launcher or child runtime applied it.
- `verified`: parent and child evidence plus denial probes matched the plan.

If any required control is missing, production activation remains blocked. Development override must not hide missing controls.
