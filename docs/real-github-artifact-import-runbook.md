# Real GitHub Artifact Import Runbook

Real import is opt-in and requires:

- managed GitHub credential secret;
- registered read-only CI origin;
- concrete workflow run ID and attempt;
- concrete artifact ID;
- exact commit;
- explicit operator execution.

Without execution the status remains:

```text
github_ci_artifact_smoke_not_configured
real_github_import_status = real_github_import_not_run
remote_ci_status = artifact_not_imported
```

Workflow success alone is not readiness.
