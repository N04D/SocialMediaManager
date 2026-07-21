# Content Framework Security

The content framework stores only safe domain metadata in content, variants, plans, and snapshots.

It does not expose:

- provider secrets
- browser session IDs
- storage references
- materialized paths
- local filesystem paths
- takeover URLs
- internal lock paths
- full remote payloads

Audit records avoid full content bodies and keep target IDs, actor, workspace, result, error code, and snapshot checksum where relevant.

Boundary tests assert that core content imports no channel or browser code, planning imports no concrete runtime, LinkedIn imports no content repositories, and snapshots contain no paths.

