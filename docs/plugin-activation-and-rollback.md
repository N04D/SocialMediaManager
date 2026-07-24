# Plugin Activation and Rollback

Activation requires installed-disabled status, fresh verification, non-revoked release, SDK compatibility, intact installed files, permission review, no built-in id collision, actor, reason, and restart. No hot activation or hot unload is provided. Rollback points activation to a previous verified, non-revoked, compatible version after explicit operator confirmation and restart.

For external plugins, activation after restart starts a version-specific plugin host environment and child process. There is no hot swap and no in-process fallback.
