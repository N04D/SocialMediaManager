from __future__ import annotations

from src.core.runtime import ExecutionAttemptLedger

from tests.test_phase76_execution_attempt_ledger import _ready_claim


def test_duplicate_active_attempt_is_prevented_and_returns_existing(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    first = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z")

    duplicate = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:02:00Z")

    assert duplicate.status == "blocked"
    assert duplicate.existing_attempt.attempt_id == first.attempt.attempt_id
    assert "active_attempt_exists" in [reason.reason_code for reason in duplicate.reasons]
    assert len(ledger.list(status="opened")) == 1


def test_same_claim_preparation_and_mode_returns_existing_active_attempt(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)

    opened = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:01:00Z")
    duplicate = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:01:30Z")

    assert duplicate.existing_attempt == opened.attempt
    assert [attempt.attempt_id for attempt in ledger.list(status="opened")] == [opened.attempt.attempt_id]


def test_different_modes_are_tracked_deterministically(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)

    noop = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    simulation = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:02:00Z").attempt

    assert noop.mode == "no_op"
    assert simulation.mode == "simulation"
    assert [attempt.attempt_id for attempt in ledger.list()] == [noop.attempt_id, simulation.attempt_id]


def test_terminal_attempt_remains_historical_and_new_attempt_can_open(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    first = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    completed = ledger.complete_noop(first.attempt_id, now="2026-08-17T15:02:00Z")

    second = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:03:00Z")

    assert completed.status == "completed_noop"
    assert second.status == "opened"
    assert len(ledger.list(status="completed_noop")) == 1
    assert len(ledger.list(status="opened")) == 1


def test_list_filters_by_status_preparation_and_claim(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    first = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    second = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:02:00Z").attempt

    assert ledger.list(status="opened") == (first, second)
    assert ledger.list(preparation_id=preparation["preparation_id"]) == (first, second)
    assert ledger.list(claim_id=claim.claim_id) == (first, second)


def test_ledger_uses_local_json_store_only(tmp_path):
    ledger = ExecutionAttemptLedger(tmp_path / "attempts.json")

    assert ledger.list() == ()
    assert (tmp_path / "attempts.json").exists() is False
