from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.core.runtime import MutationIntent, MutationReceipt, MutationState, SqliteMutationJournal


def intent() -> MutationIntent:
    return MutationIntent(
        mutation_id="mutation_phase49_concurrent",
        execution_id="exec_phase49_concurrent_a",
        node_id="create-calendar",
        capability_id="calendar.event.create",
        component_id="publication-calendar-local",
        install_id="calendar-publication-local",
        normalized_input={"occurrence_key": "phase49:concurrent", "_compensation": {"mode": "none"}},
        input_fingerprint="",
        idempotency_key="mutation:phase49:concurrent",
    )


def receipt(intent_: MutationIntent) -> MutationReceipt:
    return MutationReceipt(
        mutation_id=intent_.mutation_id,
        capability_id=intent_.capability_id,
        component_id=intent_.component_id,
        resource_ref="calendar-occurrence:phase49-concurrent",
        applied_at="2026-08-09T10:00:00+00:00",
        idempotency_key=intent_.idempotency_key,
        result_fingerprint="result",
    )


def test_concurrent_duplicate_mutation_claim_allows_one_effective_worker(tmp_path: Path) -> None:
    path = tmp_path / "runtime-mutations.sqlite3"
    first = SqliteMutationJournal(path)
    prepared = first.prepare_intent(intent())
    first.mark_approved(prepared.intent.mutation_id, approval_id="approval-1")
    effects: list[str] = []

    def worker(worker_id: str) -> bool:
        journal = SqliteMutationJournal(path)
        record = journal.prepare_intent(intent())
        claim, claimed = journal.claim_applying(record.intent.mutation_id, owner=worker_id)
        if claimed:
            effects.append(worker_id)
            journal.record_applied(receipt(record.intent))
        return claimed or claim.state in {MutationState.APPLIED.value, MutationState.APPLYING.value}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("worker-1", "worker-2")))

    final = SqliteMutationJournal(path).find_by_idempotency_key("mutation:phase49:concurrent")
    assert results == [True, True]
    assert effects == ["worker-1"] or effects == ["worker-2"]
    assert final is not None
    assert final.state == MutationState.APPLIED.value
    assert final.receipt is not None
    assert final.receipt.resource_ref == "calendar-occurrence:phase49-concurrent"


def test_duplicate_prepare_with_same_idempotency_reuses_existing_intent(tmp_path: Path) -> None:
    journal_a = SqliteMutationJournal(tmp_path / "runtime-mutations.sqlite3")
    journal_b = SqliteMutationJournal(tmp_path / "runtime-mutations.sqlite3")
    first = journal_a.prepare_intent(intent())
    duplicate = journal_b.prepare_intent(
        MutationIntent(
            mutation_id="mutation_phase49_concurrent_other_execution",
            execution_id="exec_phase49_concurrent_b",
            node_id="create-calendar",
            capability_id="calendar.event.create",
            component_id="publication-calendar-local",
            install_id="calendar-publication-local",
            normalized_input={"occurrence_key": "phase49:concurrent", "_compensation": {"mode": "none"}},
            input_fingerprint="",
            idempotency_key="mutation:phase49:concurrent",
        )
    )

    assert duplicate.intent.mutation_id == first.intent.mutation_id
    assert duplicate.intent.idempotency_key == first.intent.idempotency_key
