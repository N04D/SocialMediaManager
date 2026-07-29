# GitHub CI Evidence Operator Flow v0.1

Phase 31 connects managed GitHub credentials, registered GitHub Actions origins, concrete workflow runs, concrete artifact IDs, phase-28 evidence packages, host import attestations, independent review, and exact-commit promotion.

The flow is intentionally operator-controlled:

1. Resolve the current commit from Git.
2. Validate a managed read-only GitHub credential and origin.
3. Discover bounded workflow runs for the exact commit.
4. Select one concrete run attempt.
5. Select one concrete artifact ID.
6. Run metadata-only dry-run validation.
7. Execute a durable import request.
8. Verify provider digest, internal package checksums, provenance, required suites and required skips.
9. Create a host import attestation.
10. Require independent review when policy requires it.
11. Promote evidence only for the exact commit.

The operator service does not implement cryptography, package extraction, secret storage, GitHub parsing, HTTP downloads, retries, or a scheduler. It coordinates existing phase-28, phase-29 and phase-30 components.

Without an imported artifact, `remote_ci_status = artifact_not_imported`.
