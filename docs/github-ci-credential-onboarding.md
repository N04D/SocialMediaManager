# GitHub CI Credential Onboarding

GitHub credentials are managed secrets with type `github_read_only_token` and purpose `github_actions_read`.

Secret values may be entered only through one-time secure input or CLI stdin. They are not accepted as URL parameters, command-line token arguments, browser storage, audit comments, support bundles, evidence packages or logs.

Credential approval is resource-version and fingerprint bound. A creator cannot approve their own credential when four-eyes policy applies. Credential rotation invalidates old approvals for the new version.

The origin doctor uses the credential only through a call-scoped lease and releases it after read-only metadata checks.
