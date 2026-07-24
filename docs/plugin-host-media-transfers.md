# Plugin Host Media Transfers

Media is materialized by the controller into a call-scoped transfer with opaque transfer id, temporary path, MIME, size, checksum, and expiry. The controller chooses the path, rejects symlinks and arbitrary destinations, validates checksums, and cleans transfers after success, failure, timeout, or crash.
