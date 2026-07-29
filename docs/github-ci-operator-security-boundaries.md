# GitHub CI Operator Security Boundaries

The phase-31 flow has no GitHub write path. It does not dispatch workflows, rerun workflows, cancel workflows, delete artifacts, write repository contents, write releases or write commit statuses.

The flow does not accept `--token`, `--artifact-url`, `--force`, `--trust`, `--latest` or `--skip-verification` controls.

Provider digest verification and internal evidence package checksums are separate controls. Neither replaces repository, workflow, run attempt and commit binding.

No token, Authorization header, temporary download URL, raw response header, browser profile, content body, `content/` data or `drafts/` data is stored in the operator readmodels.

Phase 20.2 remains separately blocked until external plugin sandbox production certification is complete.
