# Managed Secret Backends

Implemented backends:

- `secret.local_encrypted`: production-like local AES-GCM vault.
- `secret.environment_read_only`: reads explicitly bound environment values only.
- `secret.in_memory_fixture`: tests only and never production-ready.

There is no silent fallback to fixture, hardcoded, or development secrets. Without explicit backend configuration, readiness reports `managed_secrets_status = not_configured`.
