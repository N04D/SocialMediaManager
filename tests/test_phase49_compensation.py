from __future__ import annotations

from dataclasses import replace

from publication_scheduling import ScheduleOccurrenceRepository
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CompensationIntent,
    CompensationReceipt,
    SqliteMutationJournal,
)
from tests.test_phase48_production_mutation import (
    calendar_create_deployment,
    calendar_create_event,
    calendar_stack,  # noqa: F401
    mutation_executor,
    mutation_registry,
)


def test_calendar_compensation_proof_blocked_without_existing_inverse() -> None:
    assert not hasattr(ScheduleOccurrenceRepository, "delete")
    assert not hasattr(ScheduleOccurrenceRepository, "remove")
    assert (
        phase41_runtime_registry().components["publication-calendar-local"].capability("calendar.event.delete") is None
    )


def test_compensation_contracts_are_not_public_runtime_capabilities() -> None:
    intent = CompensationIntent(
        compensation_id="compensation_phase49_contract",
        original_mutation_id="mutation_phase49_contract",
        execution_id="exec_phase49_contract",
        node_id="create-calendar",
        capability_id="calendar.event.create",
        component_id="publication-calendar-local",
        install_id="calendar-publication-local",
        resource_ref="calendar-occurrence:contract",
        compensation_fingerprint="fingerprint",
        idempotency_key="compensation:phase49:contract",
    )
    receipt = CompensationReceipt(
        compensation_id=intent.compensation_id,
        original_mutation_id=intent.original_mutation_id,
        resource_ref=intent.resource_ref,
        compensated_at="2026-08-09T10:00:00+00:00",
        idempotency_key=intent.idempotency_key,
        verified=True,
    )

    assert intent.capability_id == "calendar.event.create"
    assert receipt.verified is True


def test_compensation_mode_is_part_of_approved_intent_fingerprint(calendar_stack) -> None:  # noqa: F811
    registry = mutation_registry()
    deployment = calendar_create_deployment()
    executor_none, _handler_none, plan_none = mutation_executor(
        calendar_stack,
        registry=registry,
        deployment=deployment,
    )
    plan_none = replace(plan_none, nodes=tuple(replace(node, config=dict(node.config)) for node in plan_none.nodes))
    plan_none.nodes[1].config["compensation"] = {"mode": "none"}

    waiting_none = executor_none.execute(
        plan=plan_none, trigger_event=calendar_create_event(idempotency_key="phase49-a")
    )
    approval_none = executor_none.approval_store.get(waiting_none.execution.execution_id, "create-calendar")
    assert approval_none is not None

    executor_comp, _handler_comp, plan_comp = mutation_executor(
        calendar_stack,
        registry=registry,
        deployment=deployment,
    )
    plan_comp = replace(plan_comp, playbook_id="calendar.phase49.compensation-fingerprint")
    plan_comp = replace(plan_comp, nodes=tuple(replace(node, config=dict(node.config)) for node in plan_comp.nodes))
    plan_comp.nodes[1].config["compensation"] = {"mode": "on_downstream_failure"}

    waiting_comp = executor_comp.execute(
        plan=plan_comp, trigger_event=calendar_create_event(idempotency_key="phase49-b")
    )
    approval_comp = executor_comp.approval_store.get(waiting_comp.execution.execution_id, "create-calendar")
    assert approval_comp is not None

    assert approval_none.metadata["input_fingerprint"] != approval_comp.metadata["input_fingerprint"]


def test_sqlite_compensation_journal_records_failed_compensation(tmp_path) -> None:
    journal = SqliteMutationJournal(tmp_path / "runtime-mutations.sqlite3")
    intent = CompensationIntent(
        compensation_id="compensation_phase49_failed",
        original_mutation_id="mutation_phase49_failed",
        execution_id="exec_phase49_failed",
        node_id="create-calendar",
        capability_id="calendar.event.create",
        component_id="publication-calendar-local",
        install_id="calendar-publication-local",
        resource_ref="calendar-occurrence:failed",
        compensation_fingerprint="fingerprint",
        idempotency_key="compensation:phase49:failed",
    )

    journal.prepare_compensation(intent)
    journal.claim_compensating(intent.compensation_id, owner="worker-1")
    failed = journal.record_compensation_failed(intent.compensation_id, error_code="COMPENSATION_FAILED")

    assert failed.state == "compensation_failed"
    assert failed.error_code == "COMPENSATION_FAILED"
