from __future__ import annotations

import json

from tests.test_phase76_execution_attempt_ledger import _ready_claim


def test_attempt_open_duplicate_complete_fail_cancel_events_are_audited(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    opened = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:02:00Z")
    ledger.complete_noop(opened.attempt_id, now="2026-08-17T15:03:00Z")

    failed = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:04:00Z").attempt
    ledger.fail_safe(failed.attempt_id, "guard", now="2026-08-17T15:05:00Z")

    cancelled = ledger.open_attempt(claim, preparation, mode="non_production", now="2026-08-17T15:06:00Z").attempt
    ledger.cancel(cancelled.attempt_id, reason="operator", now="2026-08-17T15:07:00Z")

    event_types = [event["event_type"] for event in ledger.audit_events()]

    assert "attempt_opened" in event_types
    assert "duplicate_attempt_detected" in event_types
    assert "attempt_completed_noop" in event_types
    assert "attempt_failed_safe" in event_types
    assert "attempt_cancelled" in event_types


def test_blocked_attempt_is_audited(tmp_path):
    preparation, claim, ledger, claim_store, _ = _ready_claim(tmp_path)
    released = claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:02:00Z").claim

    blocked = ledger.open_attempt(released, preparation, now="2026-08-17T15:03:00Z")

    assert blocked.status == "blocked"
    assert "attempt_blocked" in [event["event_type"] for event in ledger.audit_events(attempt_id=blocked.attempt.attempt_id)]


def test_audit_excludes_secrets_and_raw_payloads(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, actor="worker:alpha", now="2026-08-17T15:01:00Z").attempt
    ledger.complete_noop(attempt.attempt_id, result={"summary": "local check"}, now="2026-08-17T15:02:00Z")

    rendered = json.dumps(ledger.audit_events(), sort_keys=True)

    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered
    assert all(event["redaction"]["production_mutation_used"] is False for event in ledger.audit_events())
