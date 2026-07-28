# GitHub Actions Artifact Import

Documentation basis: official GitHub REST API documentation retrieved on
2026-07-29 for workflow runs and Actions artifacts:

- `GET /repos/{owner}/{repo}/actions/runs`
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}`
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}/artifacts`
- `GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/{archive_format}`

The adapter is first-party, built-in, in-process and read-only:

```text
provider_id = "ci.github_actions"
provider_version = "0.1.0"
data_access = "read_only"
execution_mode = "built_in_in_process"
```

Workflow run success is not enough. Import requires origin trust, exact
repository and workflow identity, completed success conclusion, exact commit,
allowed branch/event, concrete artifact ID, provider digest handling, internal
package verification, freshness, review, and policy.

No workflow dispatch, rerun, cancel, artifact deletion, repository write, or
arbitrary artifact URL is supported.
