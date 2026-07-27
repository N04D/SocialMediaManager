# Publication Scheduling

Owned-publication schedules evaluate dependencies at claim time. If a LinkedIn or Mastodon occurrence is due before the website target is verified, it remains `waiting_dependency` and is re-evaluated by the existing late-occurrence policy.

Publication dependencies can block social targets until the Markdown Website target reaches `publication_verified`.

If LinkedIn or Mastodon is due while the website URL is not verified, the occurrence waits on dependency instead of publishing a stale or missing link.

Phase 23 materializes owned-publication occurrences durably with idempotency keys and atomic leases. Restart recovery releases expired leases and does not create duplicate occurrences.
