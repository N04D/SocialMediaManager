# Managed Secret Operator Roles

Roles:

- `secret_operator`: create references, enter values, request validation and rotation.
- `security_approver`: approve secrets, signer activation, revocation, and backend changes.
- `release_operator`: start CI imports and review release evidence.
- `auditor`: read metadata and audit only.
- `workspace_admin`: manage workspace policy without plaintext access.

Workspace administration does not imply access to secret values.
