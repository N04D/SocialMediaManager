from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Thread

from publication_calendar_runtime_handlers import (
    CALENDAR_COMPONENT_ID,
    CALENDAR_EVENT_CREATE_CAPABILITY,
    CalendarEventCreateHandler,
)
from src.core.runtime import (
    CompensationState,
    ExecutionContext,
    ExecutionPlanNode,
    MutationIntent,
    MutationReceipt,
    MutationState,
    PlaybookNode,
    SqliteMutationJournal,
    mutation_input_fingerprint,
    recover_compensation,
    recover_mutation,
)
from tests.test_phase48_production_mutation import calendar_create_event, calendar_stack  # noqa: F401
from tests.test_phase50_calendar_compensation import (
    EchoHandler,
    _compensation_intent_for_receipt,
    approve_waiting_mutation,
    occurrence_records,
    phase50_executor,
)


@dataclass
class CountingCompensationHandler(CalendarEventCreateHandler):
    compensation_calls: int = 0

    def compensate(self, **kwargs):  # type: ignore[no-untyped-def]
        self.compensation_calls += 1
        return super().compensate(**kwargs)


def test_crash_before_compensation_apply_can_resume_private_inverse(calendar_stack) -> None:  # noqa: F811
    executor, handler, _echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-recover-a"))
    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)
    receipt = MutationReceipt.from_dict(approved.context.node_outputs["create-calendar"]["mutation_receipt"])
    compensation = _compensation_intent_for_receipt(approved.execution.execution_id, receipt)
    journal = executor.mutation_journal
    journal.prepare_compensation(compensation)
    journal.claim_compensating(compensation.compensation_id, owner="worker-crashed")

    recovered = recover_compensation(
        journal,
        compensation.compensation_id,
        verify_compensated=lambda _intent: None,
    )
    compensation_receipt = handler.compensate(receipt=receipt, context=approved.context, compensation=compensation)
    journal.record_compensated(compensation_receipt)

    assert recovered.action == "requires_reapply"
    assert occurrence_records(calendar_stack) == []
    assert journal.get_compensation(compensation.compensation_id).state == CompensationState.COMPENSATED.value


def test_crash_after_compensation_apply_converges_without_second_effect(calendar_stack) -> None:  # noqa: F811
    executor, handler, _echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-recover-b"))
    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)
    receipt = MutationReceipt.from_dict(approved.context.node_outputs["create-calendar"]["mutation_receipt"])
    compensation = _compensation_intent_for_receipt(approved.execution.execution_id, receipt)
    journal = executor.mutation_journal
    journal.prepare_compensation(compensation)
    journal.claim_compensating(compensation.compensation_id, owner="worker-crashed")
    first = handler.compensate(receipt=receipt, context=approved.context, compensation=compensation)

    restarted = SqliteMutationJournal(Path(calendar_stack["tmp"]) / "runtime-mutations.sqlite3")
    recovered = recover_compensation(
        restarted,
        compensation.compensation_id,
        verify_compensated=lambda intent: handler.compensate(
            receipt=receipt,
            context=approved.context,
            compensation=intent,
        ),
    )

    assert first.verified is True
    assert recovered.recovered is True
    assert recovered.action == "marked_compensated"
    assert restarted.get_compensation(compensation.compensation_id).state == CompensationState.COMPENSATED.value
    assert occurrence_records(calendar_stack) == []


def test_crash_after_calendar_create_before_applied_state_recovers_with_receipt(calendar_stack) -> None:  # noqa: F811
    journal = SqliteMutationJournal(Path(calendar_stack["tmp"]) / "runtime-mutations.sqlite3")
    handler = CalendarEventCreateHandler(
        calendar_service=calendar_stack["calendar_service"],
        occurrence_repository=calendar_stack["scheduling"].occurrence_repository,
    )
    event = calendar_create_event(idempotency_key="phase50-applying-recovery", occurrence_key="phase50:applying")
    context = ExecutionContext(
        execution_id="exec_phase50_applying",
        deployment_id="phase50-calendar-compensation",
        trigger_event=event,
        correlation_id=event.correlation_id,
        trace_id=event.trace_id,
    )
    input_data = dict(event.payload)
    fingerprint = mutation_input_fingerprint({**input_data, "_compensation": {"mode": "on_downstream_failure"}})
    intent = MutationIntent(
        mutation_id="mutation_phase50_applying",
        execution_id=context.execution_id,
        node_id="create-calendar",
        capability_id=CALENDAR_EVENT_CREATE_CAPABILITY,
        component_id=CALENDAR_COMPONENT_ID,
        install_id="calendar-publication-local",
        normalized_input={**input_data, "_compensation": {"mode": "on_downstream_failure"}},
        input_fingerprint=fingerprint,
        idempotency_key="mutation:phase50:applying",
    )
    journal.prepare_intent(intent)
    journal.mark_approved(intent.mutation_id, approval_id="approval-phase50")
    journal.claim_applying(intent.mutation_id, owner=context.execution_id)
    result = handler.execute(
        context=context,
        node=PlaybookNode("create-calendar", "capability", {}),
        resolved_node=ExecutionPlanNode(
            node_id="create-calendar",
            kind="capability",
            requirement="calendar",
            capability=CALENDAR_EVENT_CREATE_CAPABILITY,
            install_id="calendar-publication-local",
            component_id=CALENDAR_COMPONENT_ID,
            provider="calendar",
        ),
        input_data={
            **input_data,
            "_runtime": {
                "idempotency_key": intent.idempotency_key,
                "input_fingerprint": intent.input_fingerprint,
                "mutation_id": intent.mutation_id,
            },
        },
    )

    recovered = recover_mutation(
        journal,
        intent.mutation_id,
        verify_applied=lambda _intent: MutationReceipt.from_dict(result.output["mutation_receipt"]),
    )
    record = journal.get(intent.mutation_id)

    assert result.status == "success"
    assert recovered.action == "marked_applied"
    assert record is not None
    assert record.state == MutationState.APPLIED.value
    assert len(occurrence_records(calendar_stack)) == 1


def test_sqlite_atomic_compensation_claim_allows_one_effective_worker(calendar_stack) -> None:  # noqa: F811
    executor, handler, _echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-concurrent"))
    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)
    receipt = MutationReceipt.from_dict(approved.context.node_outputs["create-calendar"]["mutation_receipt"])
    compensation = _compensation_intent_for_receipt(approved.execution.execution_id, receipt)
    journal = executor.mutation_journal
    journal.prepare_compensation(compensation)
    results: list[tuple[bool, str]] = []

    def worker(owner: str) -> None:
        record, claimed = journal.claim_compensating(compensation.compensation_id, owner=owner)
        if claimed:
            compensation_receipt = handler.compensate(
                receipt=receipt, context=approved.context, compensation=compensation
            )
            journal.record_compensated(compensation_receipt)
        results.append((claimed, record.state))

    threads = [Thread(target=worker, args=(f"worker-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final = journal.get_compensation(compensation.compensation_id)
    assert sum(1 for claimed, _state in results if claimed) == 1
    assert final is not None
    assert final.state == CompensationState.COMPENSATED.value
    assert occurrence_records(calendar_stack) == []
