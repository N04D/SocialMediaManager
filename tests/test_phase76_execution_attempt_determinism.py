from __future__ import annotations

from tests.test_phase76_execution_attempt_ledger import _ready_claim


def _stable_attempt(attempt):
    payload = attempt.to_dict()
    payload.pop("attempt_id", None)
    payload.pop("started_at", None)
    payload.pop("completed_at", None)
    payload["events"] = []
    return payload


def test_same_inputs_are_stable_except_ids_and_timestamps(tmp_path):
    preparation_a, claim_a, ledger_a, _, _ = _ready_claim(tmp_path / "a")
    preparation_b, claim_b, ledger_b, _, _ = _ready_claim(tmp_path / "b")
    claim_b_payload = claim_b.to_dict()
    claim_b_payload["claim_id"] = claim_a.claim_id
    preparation_b["preparation_id"] = preparation_a["preparation_id"]
    preparation_b["idempotency_key"] = preparation_a["idempotency_key"]

    first = ledger_a.open_attempt(claim_a, preparation_a, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    second = ledger_b.open_attempt(claim_b_payload, preparation_b, mode="no_op", now="2026-08-17T15:01:00Z").attempt

    assert _stable_attempt(first) == _stable_attempt(second)


def test_list_ordering_is_stable_by_started_at_then_id(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    later = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:02:00Z").attempt
    earlier = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt

    assert [attempt.attempt_id for attempt in ledger.list()] == [earlier.attempt_id, later.attempt_id]


def test_audit_ordering_is_stable(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, now="2026-08-17T15:01:00Z").attempt
    ledger.complete_noop(attempt.attempt_id, now="2026-08-17T15:02:00Z")
    ledger.cancel(attempt.attempt_id, reason="late", now="2026-08-17T15:03:00Z")

    event_types = [event["event_type"] for event in ledger.audit_events(attempt_id=attempt.attempt_id)]

    assert event_types == ["attempt_opened", "attempt_completed_noop", "invalid_transition_attempted"]
