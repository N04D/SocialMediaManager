# Plugin Revocation and Quarantine

Yanked releases are skipped for new installs by default and shown with warnings. Revoked releases cannot be installed, activated, or used for rollback; active revoked installs become attention-required. Quarantine is used for signature failure, hash mismatch, identity mismatch, manifest conflict, forbidden files, path attacks, secrets, file drift, revoked release, import failure, and policy violations. Quarantined code is not imported.
