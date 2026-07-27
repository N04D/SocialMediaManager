# Owned Publication Support Bundles

Support bundles are safe diagnostic archives. They may include version data, readiness, storage health, migration status, worker summaries, queue counts, readmodel status, integrity summaries, and checksums.

They must not include:

- raw content;
- drafts;
- database files;
- browser profiles;
- cookies;
- tokens;
- authorization headers;
- private keys;
- private remotes;
- personal absolute paths.

Bundles are generated under managed operations storage, finalized atomically, bounded by size, and include per-file checksums.
