# Certification Evidence Trust v0.1

Phase 28 adds verifiable certification evidence for owned-publication,
instrumentation and staging analytics checks.

Trust levels are explicit: `unsigned_local`, `signed_local`,
`verified_ci_artifact`, `verified_staging_provider`, `invalid`, `untrusted`,
`stale`, and `revoked`.

Remote CI is reported as `artifact_not_imported` until a real CI artifact is
imported and verified. A configured workflow is not a CI pass claim.

Phase 20.2 remains separate and `production_ready=false` until independently
certified.
