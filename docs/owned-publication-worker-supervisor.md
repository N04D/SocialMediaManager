# Owned Publication Worker Supervisor

`OwnedPublicationWorkerSupervisor` manages bounded host-owned workers:

- OccurrenceWorker
- ReconciliationWorker
- IntegrityWorker
- ReadModelWorker
- RetentionWorker

The execution model is:

```text
worker_execution_model = thread
```

Workers use bounded batches and repository claim/lease APIs. They do not replay uncertain mutations, force retries, or publish outside the existing execution services.
