# Markdown Website Channel v0.1

Phase 22 uses this channel through the Owned Publication Workspace. The workspace previews with the same deterministic renderer used for publication, binds website targets before social targets, and keeps Git evidence separate from public URL verification.

`channel.markdown_website` is a built-in `owned_publication` channel. It renders a full immutable content revision as Markdown, writes it to an allowlisted Git worktree, commits exact changed paths, optionally pushes to an allowlisted remote branch, and verifies the resulting public URL before social distribution can continue.

The plugin is not a hosting platform or static-site generator. It does not install Node.js, run build commands, deploy hosting providers, accept arbitrary paths, or force-push.

Phase 26 adds optional instrumentation bindings for Markdown Website output.
Profiles may include controlled frontmatter and a deterministic sidecar manifest
inside the authorized content root. Existing publication snapshots remain the
source of truth; draft edits do not mutate old manifests.
