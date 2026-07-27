# SocialMediaManager

SocialMediaManager turns long-form content into channel-specific publication targets.

## Markdown Website Channel

`channel.markdown_website` is the built-in owned-publication endpoint for full Markdown articles. It writes deterministic Markdown and media into an allowlisted Git worktree, commits exact mutation paths, optionally pushes to an allowlisted branch, verifies the public URL, and only then unlocks dependent LinkedIn or Mastodon distribution targets.
