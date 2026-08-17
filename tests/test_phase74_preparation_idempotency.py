from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionPreparationStore

from tests.test_phase74_preparation_store import _record


def test_same_semantic_record_has_same_idempotency_key_with_different_id_and_timestamp(tmp_path):
    first = _record(tmp_path, created_at="2026-08-17T13:00:00Z")
    second = replace(first, preparation_id="prep_other", created_at="2026-08-17T14:00:00Z")
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    assert store.idempotency_key(first) == store.idempotency_key(second)


def test_duplicate_save_returns_existing_record_and_keeps_count_one(tmp_path):
    first = _record(tmp_path, created_at="2026-08-17T13:00:00Z")
    duplicate = replace(first, preparation_id="prep_duplicate", created_at="2026-08-17T14:00:00Z")
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T15:00:00Z")

    saved = store.save(first)
    duplicate_result = store.save(duplicate)

    assert duplicate_result == saved
    assert len(store.list()) == 1
    assert [event["event_type"] for event in store.audit_events()] == ["saved", "duplicate_detected"]


def test_changed_plan_fingerprint_produces_different_key(tmp_path):
    first = _record(tmp_path)
    changed = replace(first, plan_fingerprint="plan_fingerprint_changed")
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    assert store.idempotency_key(first) != store.idempotency_key(changed)


def test_changed_action_or_scope_produces_different_key(tmp_path):
    first = _record(tmp_path)
    action_changed = replace(first, requested_action_kind="sandbox_replay")
    scope_changed = replace(first, subject_scope={**first.subject_scope, "execution_id": "different"})
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    assert store.idempotency_key(first) != store.idempotency_key(action_changed)
    assert store.idempotency_key(first) != store.idempotency_key(scope_changed)


def test_changed_capabilities_produce_different_key(tmp_path):
    first = _record(tmp_path)
    changed = replace(first, required_capabilities=("content.performance.context.read", "other.read"))
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    assert store.idempotency_key(first) != store.idempotency_key(changed)
