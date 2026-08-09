from __future__ import annotations

from pathlib import Path

from src.core.runtime import (
    CompensationIntent,
    CompensationReceipt,
    CompensationState,
    MutationIntent,
    MutationReceipt,
    MutationState,
    SqliteMutationJournal,
    recover_mutation,
)


def mutation_intent(suffix: str = "a") -> MutationIntent:
    return MutationIntent(
        mutation_id=f"mutation_phase49_{suffix}",
        execution_id=f"exec_phase49_{suffix}",
        node_id="write",
        capability_id="calendar.event.create",
        component_id="publication-calendar-local",
        install_id="calendar-publication-local",
        normalized_input={"title": "Recovery", "_compensation": {"mode": "none"}},
        input_fingerprint="",
        idempotency_key=f"mutation:phase49:{suffix}",
    )


def mutation_receipt(intent: MutationIntent) -> MutationReceipt:
    return MutationReceipt(
        mutation_id=intent.mutation_id,
        capability_id=intent.capability_id,
        component_id=intent.component_id,
        resource_ref="calendar-occurrence:phase49",
        applied_at="2026-08-09T10:00:00+00:00",
        idempotency_key=intent.idempotency_key,
        result_fingerprint="result-fingerprint",
        metadata={"readback_verified": True},
    )


def compensation_intent(intent: MutationIntent) -> CompensationIntent:
    return CompensationIntent(
        compensation_id="compensation_phase49_a",
        original_mutation_id=intent.mutation_id,
        execution_id=intent.execution_id,
        node_id=intent.node_id,
        capability_id=intent.capability_id,
        component_id=intent.component_id,
        install_id=intent.install_id,
        resource_ref="calendar-occurrence:phase49",
        compensation_fingerprint="comp-fingerprint",
        idempotency_key="compensation:phase49:a",
    )


def test_sqlite_journal_survives_restart_for_mutation_states(tmp_path: Path) -> None:
    path = tmp_path / "runtime-mutations.sqlite3"
    journal = SqliteMutationJournal(path)
    intent = mutation_intent()

    prepared = journal.prepare_intent(intent)
    approved = journal.mark_approved(intent.mutation_id, approval_id="approval-1")
    applying, claimed = journal.claim_applying(intent.mutation_id, owner="worker-1")

    restarted = SqliteMutationJournal(path)
    loaded = restarted.get(intent.mutation_id)

    assert prepared.state == MutationState.PREPARED.value
    assert approved.state == MutationState.APPROVED.value
    assert applying.state == MutationState.APPLYING.value
    assert claimed is True
    assert loaded is not None
    assert loaded.state == MutationState.APPLYING.value
    assert loaded.intent.input_fingerprint == intent.input_fingerprint


def test_recover_applying_with_readback_marks_applied(tmp_path: Path) -> None:
    journal = SqliteMutationJournal(tmp_path / "runtime-mutations.sqlite3")
    intent = mutation_intent()
    journal.prepare_intent(intent)
    journal.mark_approved(intent.mutation_id, approval_id="approval-1")
    journal.claim_applying(intent.mutation_id, owner="worker-1")

    result = recover_mutation(journal, intent.mutation_id, verify_applied=mutation_receipt)

    recovered = journal.get(intent.mutation_id)
    assert result.recovered is True
    assert result.action == "marked_applied"
    assert recovered is not None
    assert recovered.state == MutationState.APPLIED.value
    assert recovered.receipt is not None
    assert recovered.receipt.resource_ref == "calendar-occurrence:phase49"


def test_recover_applying_without_readback_returns_to_approved(tmp_path: Path) -> None:
    journal = SqliteMutationJournal(tmp_path / "runtime-mutations.sqlite3")
    intent = mutation_intent()
    journal.prepare_intent(intent)
    journal.mark_approved(intent.mutation_id, approval_id="approval-1")
    journal.claim_applying(intent.mutation_id, owner="worker-1")

    result = recover_mutation(journal, intent.mutation_id, verify_applied=lambda _intent: None)

    recovered = journal.get(intent.mutation_id)
    assert result.recovered is True
    assert result.action == "returned_to_approved"
    assert recovered is not None
    assert recovered.state == MutationState.APPROVED.value


def test_compensation_journal_survives_restart_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "runtime-mutations.sqlite3"
    journal = SqliteMutationJournal(path)
    intent = mutation_intent()
    compensation = compensation_intent(intent)
    journal.prepare_intent(intent)
    journal.record_applied(mutation_receipt(intent))

    prepared = journal.prepare_compensation(compensation)
    claim, claimed = journal.claim_compensating(compensation.compensation_id, owner="worker-1")
    receipt = CompensationReceipt(
        compensation_id=compensation.compensation_id,
        original_mutation_id=intent.mutation_id,
        resource_ref=compensation.resource_ref,
        compensated_at="2026-08-09T10:01:00+00:00",
        idempotency_key=compensation.idempotency_key,
        verified=True,
        metadata={"readback_verified": True},
    )
    journal.record_compensated(receipt)

    restarted = SqliteMutationJournal(path)
    second_claim, second_claimed = restarted.claim_compensating(compensation.compensation_id, owner="worker-2")

    assert prepared.state == CompensationState.PREPARED.value
    assert claim.state == CompensationState.COMPENSATING.value
    assert claimed is True
    assert second_claimed is False
    assert second_claim.state == CompensationState.COMPENSATED.value
    assert second_claim.receipt is not None
    assert second_claim.receipt.verified is True
