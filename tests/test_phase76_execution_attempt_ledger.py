from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionAttemptLedger, ExecutionClaimStore, ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record


def _ready_claim(tmp_path, *, claim_now: str = "2026-08-17T15:00:00Z"):
    preparation_store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    preparation = preparation_store.save(_record(tmp_path))
    claim_store = ExecutionClaimStore(
        tmp_path / "claims.json",
        preparation_store=preparation_store,
        clock=lambda: claim_now,
    )
    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now=claim_now).claim
    ledger = ExecutionAttemptLedger(tmp_path / "attempts.json", clock=lambda: "2026-08-17T15:01:00Z")
    return preparation, claim, ledger, claim_store, preparation_store


def test_active_claim_and_ready_preparation_open_attempt(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)

    result = ledger.open_attempt(claim, preparation, mode="no_op", actor="worker:alpha", now="2026-08-17T15:01:00Z")

    assert result.status == "opened"
    assert result.attempt.status == "opened"
    assert result.attempt.mode == "no_op"
    assert result.attempt.preparation_id == preparation["preparation_id"]
    assert result.attempt.claim_id == claim.claim_id
    assert result.attempt.idempotency_key == preparation["idempotency_key"]
    assert result.attempt.playbook_id == preparation["playbook_id"]
    assert result.attempt.playbook_version == preparation["playbook_version"]
    assert result.attempt.redaction.production_mutation_used is False
    assert ledger.get(result.attempt.attempt_id) == result.attempt


def test_released_and_expired_claims_are_blocked(tmp_path):
    preparation, claim, ledger, claim_store, _ = _ready_claim(tmp_path)
    released = claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:02:00Z").claim
    blocked_released = ledger.open_attempt(released, preparation, now="2026-08-17T15:03:00Z")

    _, second_claim, second_ledger, second_claim_store, _ = _ready_claim(tmp_path / "second")
    expired = second_claim_store.expire(second_claim.claim_id, now="2026-08-17T15:16:00Z").claim
    blocked_expired = second_ledger.open_attempt(expired, preparation, now="2026-08-17T15:17:00Z")

    assert blocked_released.status == "blocked"
    assert "claim_released" in [reason.reason_code for reason in blocked_released.reasons]
    assert blocked_expired.status == "blocked"
    assert "claim_expired" in [reason.reason_code for reason in blocked_expired.reasons]


def test_non_ready_preparation_and_mismatch_are_blocked(tmp_path):
    preparation, claim, ledger, _, preparation_store = _ready_claim(tmp_path)
    blocked_record = replace(
        _record(tmp_path / "blocked"),
        preparation_id="prep_blocked",
        plan_fingerprint="plan_fingerprint_blocked",
        status="blocked",
    )
    blocked_preparation = preparation_store.save(blocked_record)
    mismatch = dict(preparation)
    mismatch["preparation_id"] = "different_preparation"

    blocked = ledger.open_attempt(claim, blocked_preparation, now="2026-08-17T15:01:00Z")
    mismatched = ledger.open_attempt(claim, mismatch, now="2026-08-17T15:02:00Z")

    assert "preparation_not_ready" in [reason.reason_code for reason in blocked.reasons]
    assert "claim_preparation_mismatch" in [reason.reason_code for reason in mismatched.reasons]


def test_unsafe_action_is_blocked(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    unsafe = dict(preparation)
    unsafe["requested_action_kind"] = "publish"

    result = ledger.open_attempt(claim, unsafe, now="2026-08-17T15:01:00Z")

    assert result.status == "blocked"
    assert "unsafe_action" in [reason.reason_code for reason in result.reasons]
