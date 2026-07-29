# GitHub CI Current Commit Readiness

The current commit is resolved from local Git, not from browser input. It must be a local 40-character commit SHA.

Dirty worktree state is reported as `clean`, `dirty_user_owned_only`, `dirty_generated_only` or `dirty_other`. User-owned changes are not included in evidence packages.

Remote CI status remains `artifact_not_imported` when a workflow is configured, a run is discovered, or an artifact name exists but no artifact has been imported and promoted.

If a local commit has not been pushed, the status may be `no_remote_run_for_current_commit`; this is not a failure by itself.
