from __future__ import annotations

from src.core.runtime import ReadOnlyPlaybookSandbox, SandboxExecutionStore

from tests.test_phase65_read_only_sandbox import _plan


def test_save_event_is_recorded_without_secrets(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}],
    )
    record = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:00:00Z").execute(plan, context)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json", clock=lambda: "2026-08-16T15:01:00Z")

    store.save(record, actor="SECRET_CANARY_TESTER")

    events = store.audit_events(record.execution_id)
    rendered = str(events)
    assert len(events) == 1
    assert events[0]["event_type"] == "saved"
    assert events[0]["payload"]["playbook_id"] == record.playbook_id
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer " not in rendered
    assert "raw_metrics_payload" not in rendered


def test_audit_events_are_deterministically_ordered(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}],
    )
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json", clock=lambda: "2026-08-16T15:01:00Z")
    first = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:00:00Z").execute(plan, context)
    second = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:02:00Z").execute(plan, context)

    store.save(second)
    store.save(first)

    assert [item["occurred_at"] for item in store.audit_events()] == [
        "2026-08-16T15:01:00Z",
        "2026-08-16T15:01:00Z",
    ]
    assert [item["execution_id"] for item in store.audit_events()] == [second.execution_id, first.execution_id]
