# Execution Framework v0.1

Execution Framework v0.1 adds a provider-independent orchestration layer for prepared publication targets.

Contracts:

- `EXECUTION_FRAMEWORK_VERSION = "0.1.0"`
- `PUBLICATION_DISPATCHER_CONTRACT_VERSION = "1.0"`
- `EXECUTION_ATTEMPT_CONTRACT_VERSION = "1.0"`
- `EXECUTION_LEASE_CONTRACT_VERSION = "1.0"`
- `EXECUTION_RECONCILIATION_CONTRACT_VERSION = "1.0"`
- `EXECUTION_RETRY_POLICY_CONTRACT_VERSION = "1.0"`

The framework does not change Browser Framework v1, Media Framework v0.3, or Content Framework v0.1 contracts.

`PublicationExecutionService` selects due targets, claims leases, dispatches existing publish jobs, reconciles outcomes, recovers expired claims, and exposes execution history.

