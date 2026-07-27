# Campaign Scheduling

Campaign scheduling keeps website-first dependencies durable across restarts. Occurrences are materialized with unique idempotency keys and claimed by lease.

Conflict checks distinguish blocking errors from warnings: duplicate occurrences, account/time collisions, impossible dependencies, social targets before website verification, campaign windows, timezone ambiguity, DST transitions, cancelled predecessors, and archived campaigns.
