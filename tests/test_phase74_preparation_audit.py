from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record


def test_audit_records_saved_duplicate_cancelled_and_stale_events(tmp_path):
    first = _record(tmp_path / "a")
    duplicate = replace(first, preparation_id="prep_duplicate")
    second = replace(_record(tmp_path / "b"), preparation_id="prep_second", plan_fingerprint="plan_fingerprint_second")
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")

    store.save(first, actor="operator", reason="ready")
    store.save(duplicate)
    store.save(second)
    store.mark_cancelled(first.preparation_id, actor="operator", reason="not needed")
    store.mark_stale(second.preparation_id, actor="operator", reason="plan superseded")

    assert [event["event_type"] for event in store.audit_events()] == [
        "saved",
        "duplicate_detected",
        "saved",
        "cancelled",
        "stale",
    ]
    assert [event["event_type"] for event in store.audit_events(first.preparation_id)] == [
        "saved",
        "duplicate_detected",
        "cancelled",
    ]


def test_invalid_transition_audited_without_mutation(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    store.save(record)
    store.mark_stale(record.preparation_id)

    result = store.mark_cancelled(record.preparation_id, reason="SECRET_CANARY")

    assert result.changed is False
    assert result.status == "stale"
    assert store.audit_events(record.preparation_id)[-1]["event_type"] == "invalid_transition_attempted"
    assert store.audit_events(record.preparation_id)[-1]["reason"] == "redacted"


def test_audit_events_exclude_secrets_and_raw_payloads(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")

    store.save(record, actor="Bearer SECRET_CANARY", reason="raw_metrics_payload")
    rendered = str(store.audit_events())

    assert "SECRET_CANARY" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert store.audit_events()[0]["actor"] == "redacted"
    assert store.audit_events()[0]["redaction"]["secrets_included"] is False


def test_audit_ordering_is_deterministic(tmp_path):
    first = _record(tmp_path / "a")
    second = replace(_record(tmp_path / "b"), preparation_id="prep_second", plan_fingerprint="plan_fingerprint_second")
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")

    store.save(second)
    store.save(first)

    events = store.audit_events()

    assert [event["sequence"] for event in events] == [0, 1]
    assert events == sorted(events, key=lambda item: (item["sequence"], item["timestamp"], item["event_id"]))
