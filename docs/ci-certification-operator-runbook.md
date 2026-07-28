# CI Certification Operator Runbook

1. Register a GitHub Actions origin with repository, workflow and artifact
   allowlists.
2. Run the origin doctor.
3. Discover runs for an exact commit.
4. Select a concrete run attempt and artifact ID.
5. Run import dry-run.
6. Start the import request.
7. Let the CI import worker download and verify the package.
8. Review the attestation and package metadata.
9. Approve or reject.
10. Confirm readiness uses `artifact_imported_verified`, not workflow success
    alone.

Remote CI remains `artifact_not_imported` until an artifact is actually
imported.
