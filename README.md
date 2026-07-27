# SocialMediaManager

Phase 22 adds an Owned Publication Workspace for website-first funnels: compose a full Markdown article, create an immutable revision, preview Markdown Website output, plan website plus LinkedIn/Mastodon targets, verify the website before social distribution, reconcile uncertain states without blind retries, and inspect content-aware funnel metrics.

The workspace does not build or host a website. Git push is distinct from public URL verification, and phase 20.2 Linux sandbox certification remains separately blocked until a supported Linux host proves `linux_production_ready=true`.

Phase 23 persists owned-publication drafts, immutable revisions, variants, publication plans, evidence, reconciliation leases, campaigns, and funnel readmodels in a host-owned SQLite store.

Phase 24 adds production operations for the owned-publication stack: browser/worker CI certification, fail-on-skip release gates, worker supervision, storage health, managed SQLite backups, staged restore validation, support bundles, and a release-check command. External plugin sandbox certification from phase 20.2 remains separately blocked and is reported separately.

SocialMediaManager turns long-form content into channel-specific publication targets.

## Markdown Website Channel

`channel.markdown_website` is the built-in owned-publication endpoint for full Markdown articles. It writes deterministic Markdown and media into an allowlisted Git worktree, commits exact mutation paths, optionally pushes to an allowlisted branch, verifies the public URL, and only then unlocks dependent LinkedIn or Mastodon distribution targets.
