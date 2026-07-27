# SocialMediaManager

Phase 22 adds an Owned Publication Workspace for website-first funnels: compose a full Markdown article, create an immutable revision, preview Markdown Website output, plan website plus LinkedIn/Mastodon targets, verify the website before social distribution, reconcile uncertain states without blind retries, and inspect content-aware funnel metrics.

The workspace does not build or host a website. Git push is distinct from public URL verification, and phase 20.2 Linux sandbox certification remains separately blocked until a supported Linux host proves `linux_production_ready=true`.

SocialMediaManager turns long-form content into channel-specific publication targets.

## Markdown Website Channel

`channel.markdown_website` is the built-in owned-publication endpoint for full Markdown articles. It writes deterministic Markdown and media into an allowlisted Git worktree, commits exact mutation paths, optionally pushes to an allowlisted branch, verifies the public URL, and only then unlocks dependent LinkedIn or Mastodon distribution targets.
