from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionClaimPolicy, ExecutionClaimStore, ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record
from tests.test_phase75_execution_claim_store import _saved_ready, _stores


def _reason_codes(result):
    return [reason.reason_code for reason in result.reasons]


def test_missing_preparation_is_rejected(tmp_path):
    _, claim_store = _stores(tmp_path)

    result = claim_store.claim("missing", "worker:alpha")

    assert result.status == "rejected"
    assert "preparation_not_found" in _reason_codes(result)


def test_non_ready_preparation_statuses_are_rejected_by_default(tmp_path):
    preparation_store, claim_store = _stores(tmp_path)

    for status in ("blocked", "needs_review", "cancelled", "stale"):
        record = replace(_record(tmp_path / status), preparation_id=f"prep_{status}", status=status)
        if status in {"cancelled", "stale"}:
            saved = preparation_store.save(replace(record, status="ready"))
            if status == "cancelled":
                preparation_store.mark_cancelled(saved["preparation_id"])
            else:
                preparation_store.mark_stale(saved["preparation_id"])
            preparation_id = saved["preparation_id"]
        else:
            preparation_id = preparation_store.save(record)["preparation_id"]

        result = claim_store.claim(preparation_id, "worker:alpha")

        assert result.status == "rejected"
        assert "preparation_not_ready" in _reason_codes(result)


def test_invalid_claimant_and_claimant_kind_are_rejected(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    empty = claim_store.claim(preparation["preparation_id"], "")
    wrong_kind = claim_store.claim(
        preparation["preparation_id"],
        "operator:alpha",
        policy=ExecutionClaimPolicy(allowed_claimant_kinds=("worker",)),
    )

    assert empty.status == "rejected"
    assert wrong_kind.status == "rejected"
    assert "invalid_claimant" in _reason_codes(empty)
    assert "invalid_claimant" in _reason_codes(wrong_kind)


def test_lease_must_be_finite_positive(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    result = claim_store.claim(
        preparation["preparation_id"],
        "worker:alpha",
        policy=ExecutionClaimPolicy(lease_seconds=0),
    )

    assert result.status == "rejected"
    assert "lease_invalid" in _reason_codes(result)


def test_policy_can_block_reclaim_after_released_or_expired_claim(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    policy = ExecutionClaimPolicy(allow_reclaim_expired=False)
    first = claim_store.claim(preparation["preparation_id"], "worker:alpha", policy=policy, now="2026-08-17T15:00:00Z").claim

    claim_store.release(first.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:01:00Z")
    released_reclaim = claim_store.claim(preparation["preparation_id"], "worker:beta", policy=policy, now="2026-08-17T15:02:00Z")

    assert released_reclaim.status == "rejected"
    assert "claim_released" in _reason_codes(released_reclaim)

    second_preparation, _, second_claim_store = _saved_ready(tmp_path / "expired")
    second = second_claim_store.claim(second_preparation["preparation_id"], "worker:alpha", policy=policy, now="2026-08-17T15:00:00Z").claim
    second_claim_store.expire(second.claim_id, now="2026-08-17T15:16:00Z")
    expired_reclaim = second_claim_store.claim(second_preparation["preparation_id"], "worker:beta", policy=policy, now="2026-08-17T15:17:00Z")

    assert expired_reclaim.status == "rejected"
    assert "claim_expired" in _reason_codes(expired_reclaim)


def test_unsafe_redaction_rejects_claim(tmp_path):
    preparation_store = ExecutionPreparationStore(tmp_path / "preparations.json")
    record = _record(tmp_path)
    unsafe = {
        **record.to_dict(),
        "redaction": {**record.redaction.__dict__, "secrets_included": True},
    }
    preparation_store.save(record)
    state = preparation_store._load_state()
    saved = next(iter(state["records"].values()))
    saved["redaction"]["secrets_included"] = True
    state["records"][saved["preparation_id"]] = saved
    preparation_store._write_state(state)
    claim_store = ExecutionClaimStore(tmp_path / "claims.json", preparation_store=preparation_store)

    result = claim_store.claim(saved["preparation_id"], "worker:alpha")

    assert result.status == "rejected"
    assert "unsafe_redaction" in _reason_codes(result)
