# Certification Evidence Operator Controls

Operators can review evidence, compare local and CI packages, revoke signers or
packages, and inspect CI import attestations.

Review cannot make technically invalid evidence valid. CI evidence awaiting
review does not satisfy readiness until policy requirements are met.

Secret-backed signer activation and CI credential approval are four-eyes
actions in phase 30. Operator review cannot reveal or export secret values, and
approval cannot override technical invalidity.

## Phase 31 Reviews

GitHub CI evidence promotions are exact-commit bindings. Operator review can
approve, reject, or request follow-up, but it cannot turn a technically invalid
package into valid evidence and cannot promote evidence across commits.
