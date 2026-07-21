# Schedule Authorization

Schedules support two authorization modes:

- `per_occurrence_confirmation`
- `bounded_schedule_authorization`

`per_occurrence_confirmation` is the default. It materializes concrete targets that still require phase-13 queue confirmation.

Bounded authorization is finite and snapshot-bound. It requires:

- immutable template snapshot;
- pinned revision;
- fixed account and capability set;
- `maximum_occurrences`;
- `valid_until`;
- active kill-switch checks in execution;
- uncertain policy that pauses or requires review.

Authorization is invalidated when template checksum, generation, revision, variant, media relations, requirements, recurrence, timezone, or account/capability binding changes. No reusable public token is stored in schedule, occurrence, target, audit, or event records.
