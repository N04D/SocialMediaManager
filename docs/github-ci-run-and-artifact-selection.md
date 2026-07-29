# GitHub CI Run And Artifact Selection

Runs are discovered for an exact commit SHA. A workflow run must match repository identity, workflow identity, branch, event, status, conclusion, run ID and run attempt.

Run attempt is part of the trust binding. Attempt 1 artifacts are not automatically valid for attempt 2.

Artifacts are listed only for the selected run attempt. Artifact name is display and filtering metadata, not identity. The concrete identity is:

`origin_reference_id + run_id + run_attempt + artifact_id`

The operator flow never selects an artifact solely by name and never implicitly selects a latest run.
