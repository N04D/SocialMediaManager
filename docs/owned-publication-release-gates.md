# Owned Publication Release Gates

The release gate requires:

```text
browser_certification_passed
worker_certification_passed
required_certification_skips == 0
storage_ready
migrations_current
latest_backup_valid
restore_validation_current
required_workers_ready
no_blocking_integrity_findings
```

`scripts/owned-publication-certify.py` runs only the required phase-23.1 certification suites and treats required skips as failure.

CI artifacts are safe JSON reports. They do not include cookies, authorization headers, tokens, private keys, private remotes, raw databases, browser profiles, or user-owned content.
