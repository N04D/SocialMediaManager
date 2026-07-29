# Managed Secret Security Boundaries

Not supported:

- plaintext secrets in the app database;
- secret export;
- `--token` or `--private-key` CLI arguments;
- arbitrary vault paths;
- fixture backend as production fallback;
- GitHub write permissions;
- workflow dispatch, rerun, cancel, or artifact deletion.

Support bundles contain only safe metadata, statuses, fingerprints, and health codes.
