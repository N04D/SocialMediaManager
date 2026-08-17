from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionClaimPolicy, ExecutionClaimStore, ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record
from tests.test_phase75_execution_claim_store import _saved_ready


def _stable_result(result):
    payload = result.to_dict()
    for key in ("claim", "existing_claim"):
        if payload.get(key):
            payload[key].pop("claim_id", None)
            payload[key].pop("claimed_at", None)
            payload[key].pop("lease_expires_at", None)
    return payload


def test_same_inputs_are_stable_except_claim_id_and_timestamps(tmp_path):
    first_preparation, _, first_claim_store = _saved_ready(tmp_path / "a")
    second_preparation, _, second_claim_store = _saved_ready(tmp_path / "b")

    first = first_claim_store.claim(first_preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z")
    second = second_claim_store.claim(second_preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z")

    assert _stable_result(first) == _stable_result(second)


def test_list_ordering_is_stable(tmp_path):
    preparation_store = ExecutionPreparationStore(tmp_path / "preparations.json")
    first = preparation_store.save(_record(tmp_path / "a", created_at="2026-08-17T13:00:00Z"))
    second = preparation_store.save(
        replace(_record(tmp_path / "b", created_at="2026-08-17T13:01:00Z"), plan_fingerprint="plan_fingerprint_second")
    )
    claim_store = ExecutionClaimStore(tmp_path / "claims.json", preparation_store=preparation_store)

    later = claim_store.claim(second["preparation_id"], "worker:beta", now="2026-08-17T15:02:00Z").claim
    earlier = claim_store.claim(first["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim

    assert [claim.claim_id for claim in claim_store.list()] == [earlier.claim_id, later.claim_id]


def test_audit_ordering_is_stable(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:01:00Z")

    events = claim_store.audit_events()

    assert events == tuple(sorted(events, key=lambda item: (item["sequence"], item["timestamp"], item["event_id"])))


def test_policy_serialization_is_deterministic():
    policy = ExecutionClaimPolicy(allowed_claimant_kinds=("worker", "agent"), lease_seconds=120)

    assert policy.to_dict() == {
        "allow_reclaim_expired": True,
        "allowed_claimant_kinds": ["worker", "agent"],
        "lease_seconds": 120,
        "policy_id": "execution-claim-default",
        "require_ready_status": True,
        "version": "1.0.0",
    }
