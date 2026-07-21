# Execution Calendar

`ExecutionCalendarService` is a read-only projection.

It lists:

- projected or materialized occurrences;
- publication plans;
- publication targets;
- execution attempts;
- blackout windows when present;
- campaign context.

The calendar does not create or modify schedules, plans, targets, jobs, leases, attempts, or remote publications.

Filters:

- date range;
- presentation timezone;
- channel;
- account;
- campaign;
- schedule;
- status;
- attention-required;
- projected versus concrete.

Responses contain safe IDs, status, timestamps, short summaries, blockers, and context references. They exclude content body, storage references, local paths, browser session IDs, provider secrets, confirmation tokens, and remote payloads.
