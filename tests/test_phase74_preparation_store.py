from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionPreparationBuilder, ExecutionPreparationStore

from tests.test_phase73_execution_preparation import _ready_inputs


def _record(tmp_path, *, created_at: str = "2026-08-17T13:00:00Z"):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    return ExecutionPreparationBuilder(clock=lambda: created_at).prepare(eligibility, approval, promotion, plan)


def test_save_get_preparation_and_idempotency_key(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")

    saved = store.save(record, actor="tester")
    loaded = store.get(record.preparation_id)

    assert loaded == saved
    assert loaded["preparation_id"] == record.preparation_id
    assert loaded["status"] == "ready"
    assert loaded["store_status"] == "ready"
    assert loaded["store_schema_version"] == "execution-preparation-store.v1"
    assert loaded["idempotency_key"] == store.idempotency_key(record)


def test_get_by_idempotency_key(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json")
    saved = store.save(record)

    loaded = store.get_by_idempotency_key(saved["idempotency_key"])

    assert loaded == saved


def test_list_by_status_playbook_approval_and_deterministic_order(tmp_path):
    first = _record(tmp_path / "a", created_at="2026-08-17T13:00:00Z")
    second = replace(
        _record(tmp_path / "b", created_at="2026-08-17T13:01:00Z"),
        preparation_id="prep_second",
        plan_fingerprint="plan_fingerprint_second",
    )
    review = replace(second, preparation_id="prep_review", status="needs_review", plan_fingerprint="plan_fingerprint_review")
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    store.save(second)
    store.save(first)
    store.save(review)

    assert [item["preparation_id"] for item in store.list()] == [first.preparation_id, review.preparation_id, second.preparation_id]
    assert [item["preparation_id"] for item in store.list(status="ready")] == [first.preparation_id, second.preparation_id]
    assert store.list(playbook_id=first.playbook_id)[0]["playbook_id"] == first.playbook_id
    assert store.list(approval_id=first.approval_id)[0]["approval_id"] == first.approval_id


def test_ready_and_needs_review_can_be_cancelled_or_marked_stale(tmp_path):
    ready = _record(tmp_path)
    review = replace(ready, preparation_id="prep_review", status="needs_review", plan_fingerprint="plan_fingerprint_review")
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    store.save(ready)
    store.save(review)

    cancelled = store.mark_cancelled(ready.preparation_id, actor="operator", reason="superseded")
    stale = store.mark_stale(review.preparation_id, actor="operator", reason="plan changed")

    assert cancelled.changed is True
    assert cancelled.status == "cancelled"
    assert cancelled.record["status"] == "cancelled"
    assert stale.changed is True
    assert stale.status == "stale"
    assert stale.record["status"] == "stale"


def test_blocked_can_be_marked_stale_but_not_cancelled(tmp_path):
    blocked = replace(_record(tmp_path), preparation_id="prep_blocked", status="blocked")
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    store.save(blocked)

    cancelled = store.mark_cancelled(blocked.preparation_id)
    stale = store.mark_stale(blocked.preparation_id)

    assert cancelled.changed is False
    assert cancelled.status == "blocked"
    assert stale.changed is True
    assert stale.status == "stale"


def test_terminal_transition_is_rejected_without_status_mutation(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    store.save(record)
    stale = store.mark_stale(record.preparation_id).record

    result = store.mark_cancelled(record.preparation_id, actor="operator")

    assert stale["status"] == "stale"
    assert result.changed is False
    assert result.status == "stale"
    assert store.get(record.preparation_id)["status"] == "stale"
