# Markdown Website Operations

Run `plugin-sdk markdown-website profiles` to inspect frontmatter profiles, `plugin-sdk markdown-website render <fixture>` for deterministic preview output, and `plugin-sdk markdown-website doctor` for local contract checks.

Use reconciliation after interrupted commits or pushes. Uncertain pushes are not blindly retried; the repository and remote branch are read before deciding the next action.
