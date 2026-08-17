from __future__ import annotations

import json

from src.core.runtime import ExecutionAttemptLedger

from tests.test_phase76_execution_attempt_ledger import _ready_claim


def test_opened_attempt_can_complete_noop_with_safe_result(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, now="2026-08-17T15:01:00Z").attempt

    completed = ledger.complete_noop(attempt.attempt_id, result={"note": "dry local check"}, now="2026-08-17T15:02:00Z")

    assert completed.status == "completed_noop"
    assert completed.attempt.result["completed"] is True
    assert completed.attempt.result["side_effects"] is False
    assert completed.attempt.result["production_mutation_used"] is False
    assert completed.attempt.result["external_write_used"] is False
    assert completed.attempt.result["ai_call_used"] is False
    assert completed.attempt.result["raw_access_used"] is False


def test_opened_attempt_can_fail_safe_or_cancel(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    failed_attempt = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    cancelled_attempt = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:02:00Z").attempt

    failed = ledger.fail_safe(failed_attempt.attempt_id, "local guard tripped", now="2026-08-17T15:03:00Z")
    cancelled = ledger.cancel(cancelled_attempt.attempt_id, reason="operator cancelled", now="2026-08-17T15:04:00Z")

    assert failed.status == "failed_safe"
    assert cancelled.status == "cancelled"


def test_terminal_transitions_are_rejected_and_audited(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, now="2026-08-17T15:01:00Z").attempt
    completed = ledger.complete_noop(attempt.attempt_id, now="2026-08-17T15:02:00Z").attempt

    rejected = ledger.cancel(completed.attempt_id, reason="too late", now="2026-08-17T15:03:00Z")

    assert rejected.status == "completed_noop"
    assert "invalid_transition_attempted" in [reason.reason_code for reason in rejected.reasons]
    assert ledger.get(completed.attempt_id).status == "completed_noop"
    assert "invalid_transition_attempted" in [event["event_type"] for event in ledger.audit_events(attempt_id=completed.attempt_id)]


def test_attempt_records_and_events_do_not_leak_canaries(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, now="2026-08-17T15:01:00Z").attempt
    ledger.complete_noop(attempt.attempt_id, result={"note": "SECRET_CANARY Bearer token"}, now="2026-08-17T15:02:00Z")

    rendered = json.dumps([item.to_dict() for item in ledger.list()], sort_keys=True)
    rendered_events = json.dumps(ledger.audit_events(), sort_keys=True)

    assert "SECRET_CANARY" not in rendered
    assert "Bearer" not in rendered
    assert "Authorization" not in rendered_events
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_unsafe_result_side_effect_marker_is_sanitized(tmp_path):
    preparation, claim, ledger, _, _ = _ready_claim(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, now="2026-08-17T15:01:00Z").attempt

    completed = ledger.complete_noop(attempt.attempt_id, result={"side_effects": True}, now="2026-08-17T15:02:00Z")

    assert completed.attempt.result["side_effects"] is False


def test_source_does_not_reference_production_execution_or_remote_paths():
    source = __import__("src.core.runtime.execution_attempt_ledger", fromlist=["ExecutionAttemptLedger"])
    path = source.__file__
    text = open(path, encoding="utf-8").read()

    forbidden = (
        "PlaybookExecutor",
        "OpenAI",
        "Anthropic",
        "ChatGPT",
        "requests.",
        "subprocess",
        "youtube.metrics.read",
    )
    assert all(marker not in text for marker in forbidden)
