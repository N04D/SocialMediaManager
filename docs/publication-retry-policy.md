# Publication Retry Policy

Retry decisions depend on phase and mutation state.

Automatic retry is only allowed before remote mutation, for bounded transient situations such as queue unavailability, database locks, provider transient failure, rate limits before mutation, or worker shutdown before mutation.

No automatic retry is allowed when mutation may have started, verification is uncertain, content is stale, a snapshot mismatches, auth is missing, a kill switch is active, or a previous successful publication exists.

The policy returns a `RetryDecision` with action, automatic flag, delay, next retry time, revalidation requirement, confirmation requirement, and reason code.

