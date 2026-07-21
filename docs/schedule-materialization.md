# Schedule Materialization

`ScheduleMaterializationService` is the central service for recurrence preview, horizon materialization, occurrence creation, and schedule reconciliation.

Materialization flow:

1. load schedule, recurrence, policy, and immutable template snapshot;
2. project occurrences within the configured horizon;
3. compute deterministic occurrence keys;
4. skip existing keys;
5. apply exclusions and overlap policy;
6. validate bounded authorization when configured;
7. create a concrete `PublicationPlan`;
8. create concrete `PublicationTarget` records with resolved UTC scheduled times;
9. link the occurrence to the concrete plan and targets;
10. write events and audit.

The service uses `PublicationPlanningService`; it does not import channel runtimes, browser providers, or execution repositories.

Worker order is:

1. bounded schedule materialization;
2. phase-13 due-target dispatch;
3. existing channel job processing.
