# Scheduling Security

Scheduling records and responses must not expose:

- authorization secrets;
- confirmation tokens;
- content body in general calendar responses;
- storage references;
- local paths;
- browser session IDs;
- provider secrets;
- full remote payloads;
- internal lock files.

Scheduling services do not import concrete channel runtimes or browser providers. They do not open browsers and do not publish directly.

Audit records contain safe IDs, actor or system, workspace, action, reason, result, safe error code, timestamp, and shortened checksum where relevant.

Safe reconciliation may update derived status, mark expired authorization, rebuild materialized-until, restore an unambiguous occurrence-plan backlink, or pause a schedule after uncertain execution according to policy. It never publishes, deletes remote content, creates new authorization, or removes duplicate occurrence records automatically.
