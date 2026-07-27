# Reconciliation Operations

The reconciliation queue covers `push_uncertain`, `remote_commit_unknown`, `deployment_pending`, `public_url_mismatch`, `revision_marker_mismatch`, `canonical_mismatch`, `content_drift`, `media_missing`, `dependency_stalled`, `social_publish_uncertain`, and `analytics_attribution_issue`.

Allowed automatic actions are read-only checks and derived readmodel repairs. Reconciliation does not retry uncertain pushes, create commits, force-push, overwrite content, republish social posts, delete publications, change slugs, or bypass dependencies.
