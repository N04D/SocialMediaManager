# Owned Publication Backup And Restore

Backups use the SQLite backup API and write to a managed temporary file before atomic finalization.

The only v0.1 backup destination reference is:

```text
local-managed
```

Public APIs and CLI commands do not accept arbitrary database paths, shell commands, URLs, network shares, or cloud credentials.

Restore validation is read-only:

1. Verify backup checksum.
2. Copy the backup into a temporary restore database.
3. Check migration compatibility.
4. Run foreign-key and integrity checks.
5. Rebuild one readmodel.
6. Delete the temporary restore.

Active database replacement remains an explicit operator runbook and is not exposed as a one-call API.
