# Certification Evidence Framework

Phase 28 introduced canonical evidence packages. Phase 29 makes them
operational with host-owned Ed25519 signing and CI artifact import.

Evidence remains valid only for its explicit commit binding. Imported CI
artifacts do not become trusted because a workflow succeeded; they must pass
CI-origin, run, artifact, digest, package, signature, freshness and review
checks.
