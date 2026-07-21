# Publication Recurrence

Supported recurrence frequencies:

- `once`
- `daily`
- `weekly`
- `monthly`

Supported rule fields:

- `interval`
- `by_weekday` for weekly schedules, using Python weekday numbers where Monday is `0`
- `by_month_day` for monthly schedules
- optional `count`
- optional `until`

Unsupported fields are intentionally rejected instead of interpreted as cron or full RRULE syntax. Preview and materialization are bounded. Defaults are a 30-day horizon, at most 100 materialized occurrences per schedule, and at most 50 per materialization run.

Monthly invalid dates use explicit policy:

- `skip_invalid_date`, the default
- `last_valid_day`

Occurrence keys are deterministic SHA-256 hashes over schedule ID, generation version, resolved UTC time, and template snapshot checksum. This prevents duplicate concrete plans for the same occurrence.
