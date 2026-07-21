# Scheduling Framework v0.1

Phase 14 introduces bounded scheduling above the existing planning and execution layers.

Contracts:

- `SCHEDULING_FRAMEWORK_VERSION = "0.1.0"`
- `PUBLICATION_SCHEDULE_CONTRACT_VERSION = "1.0"`
- `RECURRENCE_RULE_CONTRACT_VERSION = "1.0"`
- `SCHEDULE_OCCURRENCE_CONTRACT_VERSION = "1.0"`
- `SCHEDULE_POLICY_CONTRACT_VERSION = "1.0"`
- `SCHEDULE_AUTHORIZATION_CONTRACT_VERSION = "1.0"`
- `EXECUTION_CALENDAR_CONTRACT_VERSION = "1.0"`
- `CAMPAIGN_CONTRACT_VERSION = "1.0"`

The scheduling layer does not publish, claim execution targets, open browsers, or create a second job queue. It projects recurrence, materializes concrete `PublicationPlan` and `PublicationTarget` records, and hands those targets to the phase-13 dispatcher.

Core source of truth:

- `PublicationSchedule`: recurring intent and policy links.
- `RecurrenceRule`: normalized controlled recurrence subset.
- `ScheduleTemplateSnapshot`: immutable template copied from a validated publication plan.
- `ScheduleOccurrence`: one resolved schedule occurrence.
- Concrete `PublicationPlan` and `PublicationTarget`: execution-ready records.
- `ExecutionAttempt`: execution history owned by phase 13.

JSON repositories are stored in `studio_data` and use the same locked-store convention as planning and execution.
