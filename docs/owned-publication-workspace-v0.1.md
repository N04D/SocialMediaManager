# Owned Publication Workspace v0.1

The Owned Publication Workspace gives one workflow for article composition, Markdown Website publication, social distribution, reconciliation, and funnel analysis.

Flow:

```text
Compose -> Validate -> Preview -> Plan -> Publish website -> Verify website -> Unlock social -> Publish social -> Measure funnel -> Analyze
```

Drafts are mutable. Content revisions, channel variant snapshots, and publication snapshots are immutable. A draft changed after scheduling does not silently change a planned publication; replacing the snapshot is an explicit action.

Phase 23 backs these workflows with durable SQLite repositories. Autosave writes only mutable draft fields with optimistic concurrency; revisions, snapshots, and evidence remain immutable across restarts.

Phase 20.2 Linux sandbox certification remains separately blocked on this machine and is not marked production-ready by this workspace.
