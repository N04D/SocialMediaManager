from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionClaimStore, ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record


def _stores(tmp_path):
    preparation_store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    claim_store = ExecutionClaimStore(
        tmp_path / "claims.json",
        preparation_store=preparation_store,
        clock=lambda: "2026-08-17T15:00:00Z",
    )
    return preparation_store, claim_store


def _saved_ready(tmp_path):
    preparation_store, claim_store = _stores(tmp_path)
    record = _record(tmp_path)
    saved = preparation_store.save(record)
    return saved, preparation_store, claim_store


def test_ready_preparation_can_be_claimed(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    result = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z")

    assert result.status == "claimed"
    assert result.claim.status == "claimed"
    assert result.claim.preparation_id == preparation["preparation_id"]
    assert result.claim.idempotency_key == preparation["idempotency_key"]
    assert result.claim.claimant_id == "worker:alpha"
    assert result.claim.lease_expires_at == "2026-08-17T15:15:00Z"
    assert result.claim.redaction.execution_started is False


def test_active_claim_blocks_duplicate_and_get_active_returns_claim(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    first = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z")

    duplicate = claim_store.claim(preparation["preparation_id"], "worker:beta", now="2026-08-17T15:01:00Z")
    active = claim_store.get_active_for_preparation(preparation["preparation_id"], now="2026-08-17T15:02:00Z")

    assert duplicate.status == "rejected"
    assert duplicate.existing_claim.claim_id == first.claim.claim_id
    assert "already_claimed" in [reason.reason_code for reason in duplicate.reasons]
    assert active.claim_id == first.claim.claim_id


def test_released_claim_allows_reclaim_by_default(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    first = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim

    released = claim_store.release(first.claim_id, claimant_id="worker:alpha", reason="yield", now="2026-08-17T15:02:00Z")
    second = claim_store.claim(preparation["preparation_id"], "worker:beta", now="2026-08-17T15:03:00Z")

    assert released.status == "released"
    assert second.status == "claimed"
    assert second.claim.claim_id != first.claim_id


def test_expired_claim_allows_reclaim_by_default(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    first = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim

    expired = claim_store.expire(first.claim_id, now="2026-08-17T15:16:00Z")
    second = claim_store.claim(preparation["preparation_id"], "worker:beta", now="2026-08-17T15:17:00Z")

    assert expired.status == "expired"
    assert second.status == "claimed"


def test_list_and_get_are_deterministic(tmp_path):
    preparation_store, claim_store = _stores(tmp_path)
    first = preparation_store.save(_record(tmp_path / "a", created_at="2026-08-17T13:00:00Z"))
    second_record = replace(_record(tmp_path / "b", created_at="2026-08-17T13:01:00Z"), plan_fingerprint="plan_fingerprint_second")
    second = preparation_store.save(second_record)

    later = claim_store.claim(second["preparation_id"], "worker:beta", now="2026-08-17T15:02:00Z").claim
    earlier = claim_store.claim(first["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim

    assert claim_store.get(earlier.claim_id) == earlier
    assert [claim.claim_id for claim in claim_store.list()] == [earlier.claim_id, later.claim_id]
    assert claim_store.list(status="claimed") == (earlier, later)
    assert claim_store.list(preparation_id=first["preparation_id"]) == (earlier,)
    assert claim_store.list(claimant_id="worker:beta") == (later,)
