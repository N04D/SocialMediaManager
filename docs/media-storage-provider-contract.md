# Media Storage Provider Contract

The v1 storage contract is synchronous in this codebase and stable for phase 9.

## Methods

`health_check()` is read-only and returns safe health, capabilities, and contract versions.

`store(source, options)` stores bytes from a controlled `MediaInput`. It validates size, MIME allowlist, checksum, and returns `StoredMedia` with an opaque storage reference. It is not idempotent unless a provider explicitly supports an idempotency key.

`exists(storage_reference)` checks object presence without exposing a path.

`stat(storage_reference)` returns `MediaObjectMetadata`.

`open_stream(storage_reference)` yields bounded byte chunks.

`materialize(storage_reference, options)` creates a temporary local file for a controlled purpose.

`cleanup_materialization(materialization)` removes that temporary file idempotently.

`delete(storage_reference, options)` physically deletes only when explicitly called by trusted code. User-facing deletion defaults to soft delete at the asset layer.

## Security

- storage references are opaque;
- object paths never use original filenames;
- local writes are partial-file then atomic replace;
- SHA-256 is the default checksum;
- materializations live outside the object store;
- provider errors are translated to media errors;
- channels must not import concrete storage providers.
