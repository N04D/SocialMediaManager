# Schedule Timezones And DST

Schedules require an explicit IANA timezone ID. The local machine timezone is never used as an implicit default.

Stored time data:

- original local schedule time
- timezone ID
- resolved UTC timestamp
- DST resolution policy

Ambiguous DST times require explicit policy:

- `first_occurrence`
- `second_occurrence`
- `require_review`

Nonexistent DST times support:

- `skip`
- `shift_forward`
- `require_review`, the default

Preview reports DST status and does not write records. Materialization refuses unresolved local times rather than silently correcting them.
