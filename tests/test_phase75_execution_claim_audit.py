from __future__ import annotations

from src.core.runtime import ExecutionClaimStore

from tests.test_phase75_execution_claim_store import _saved_ready


def test_audit_records_created_duplicate_released_expired_and_rejected(tmp_path):
    preparation, preparation_store, claim_store = _saved_ready(tmp_path)
    first = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    claim_store.claim(preparation["preparation_id"], "worker:beta", now="2026-08-17T15:01:00Z")
    claim_store.release(first.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:02:00Z")
    second = claim_store.claim(preparation["preparation_id"], "worker:gamma", now="2026-08-17T15:03:00Z").claim
    claim_store.expire(second.claim_id, now="2026-08-17T15:20:00Z")
    claim_store.claim("missing", "worker:delta", now="2026-08-17T15:21:00Z")

    assert [event["event_type"] for event in claim_store.audit_events()] == [
        "claim_created",
        "duplicate_claim_rejected",
        "claim_released",
        "claim_created",
        "claim_expired",
        "claim_rejected",
    ]
    assert [event["event_type"] for event in claim_store.audit_events(preparation_id=preparation["preparation_id"])] == [
        "claim_created",
        "duplicate_claim_rejected",
        "claim_released",
        "claim_created",
        "claim_expired",
    ]


def test_invalid_transition_is_audited_without_state_mutation(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    released = claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:02:00Z").claim

    result = claim_store.expire(claim.claim_id, now="2026-08-17T15:20:00Z")

    assert result.status == "released"
    assert result.claim == released
    assert claim_store.audit_events(claim_id=claim.claim_id)[-1]["event_type"] == "invalid_transition_attempted"


def test_audit_excludes_secret_and_raw_canaries(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    claim_store.claim(preparation["preparation_id"], "Bearer SECRET_CANARY", now="2026-08-17T15:00:00Z")
    events = claim_store.audit_events()
    rendered = str(events)

    assert "SECRET_CANARY" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert events[0]["claimant_id"] == "redacted"
    assert events[0]["redaction"]["secrets_included"] is False


def test_audit_ordering_is_deterministic(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:01:00Z")

    events = claim_store.audit_events()

    assert [event["sequence"] for event in events] == [0, 1]
    assert events == tuple(sorted(events, key=lambda item: (item["sequence"], item["timestamp"], item["event_id"])))
