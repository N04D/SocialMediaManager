# Managed Secret Master Keys

The master key is never stored in the application database, vault records, Git, support bundles, evidence, UI, API, or CLI output.

Supported sources:

- `environment_master_key` via host-owned `SMM_MANAGED_SECRET_MASTER_KEY`;
- `managed_key_file` via host configuration only;
- `ephemeral_test_key` for tests.

Unexpected master-key drift locks secret reads and degrades readiness. The implementation does not try alternate keys or recovery guesses.
