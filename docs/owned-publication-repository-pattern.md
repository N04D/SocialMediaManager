# Owned Publication Repository Pattern

Domain models do not know SQL. Dashboard routes, CLI commands, and MCP calls use `OwnedPublicationWorkspaceService`, which delegates durable operations to `DatabaseOwnedPublicationRepository`.

The repository is workspace-scoped, owns transactions, enforces idempotency keys, records audit events, and exposes typed methods rather than arbitrary SQL.
