# Analytics Security and Privacy

Analytics stores publication-level performance only.

It does not store viewer identities, liker identities, commenter profiles, contact details, DMs, cookies, credentials, browser session IDs, takeover URLs, screenshots paths, HTML bodies, storage references, or materialized local paths.

Safe APIs expose IDs, metric keys, values, timestamps, attribution dimensions, freshness, completeness, warnings, sample sizes, and shortened checksums.

Audit records capture actor, workspace, target IDs, action, timestamp, reason, result, safe error code, and shortened checksums where relevant. They do not duplicate full content bodies.

Retention is policy-based. Phase 15 does not perform destructive bulk cleanup.
