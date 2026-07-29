# Managed Secrets v0.1

Phase 30 adds a host-owned managed secret facade. Consumers receive only a `secretref:*` reference and a purpose-bound lease. Secret values are never returned through UI, API, CLI, MCP, support bundles, evidence packages, or audit records.

The local production-like backend stores encrypted records outside the application database. The database stores metadata only: reference ID, type, backend ID, status, purposes, safe fingerprint, approvals, health, consumers, and audit.

Python cannot guarantee absolute memory zeroization. The implementation keeps leases short, uses mutable buffers where practical, avoids repr/logging of values, and clears lease buffers on release as a best-effort control.

Phase 20.2 remains separately blocked; managed secrets do not certify the external plugin sandbox.
