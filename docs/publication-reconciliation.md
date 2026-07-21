# Publication Reconciliation

Reconciliation compares publication targets, execution attempts, leases, publish jobs, and published-post evidence.

Classifications include:

- `consistent_pending`
- `consistent_running`
- `consistent_succeeded`
- `consistent_failed`
- `consistent_uncertain`
- `lease_expired_pre_mutation`
- `lease_expired_post_mutation`
- `job_missing`
- `job_succeeded_evidence_missing`
- `duplicate_job_detected`
- `snapshot_mismatch`
- `manual_review_required`

Safe repairs include copying terminal job state to attempts and targets, restoring a queued target when the job is missing, and deriving aggregate plan status.

Reconciliation never publishes, retries uncertain results, deletes remote content, or removes evidence.

