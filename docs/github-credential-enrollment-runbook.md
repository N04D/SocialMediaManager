# GitHub Credential Enrollment Runbook

1. Create a `github_read_only_token` reference with purpose `github_actions_read`.
2. Enter the token through hidden input, stdin, or a managed import reference.
3. Validate and approve the secret.
4. Bind the reference to a registered GitHub Actions origin.
5. Run the origin doctor.
6. Perform dry-run import validation.

The doctor performs read-only checks and does not probe write permissions.
