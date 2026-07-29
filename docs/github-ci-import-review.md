# GitHub CI Import Review

Dry-run is metadata-only. It does not download an artifact, create evidence, create an import attestation or change readiness.

Before execution, run and artifact metadata are fetched again. If metadata changed since dry-run, execution blocks.

Download redirect URLs are treated as short-lived and are not stored, logged, returned to UI/CLI/MCP, included in evidence or included in support bundles.

Review can approve, reject or request follow-up. Review cannot override checksum mismatch, wrong commit, expired artifact, nonzero required skips, unknown signer, invalid package or production/fork policy.
