from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ReadOnlyPlaybookSandbox, SandboxExecutionStore

from tests.test_phase65_read_only_sandbox import _plan


def _record(tmp_path, *, executed_at: str = "2026-08-16T15:00:00Z"):
    context, plan = _plan(
        tmp_path,
        [
            {"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"},
            {"step_id": "metrics", "name": "Metrics", "kind": "check_metrics_available"},
        ],
    )
    return context, plan, ReadOnlyPlaybookSandbox(clock=lambda: executed_at).execute(plan, context)


def test_save_get_execution_and_persisted_fingerprint(tmp_path):
    _, _, record = _record(tmp_path)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json", clock=lambda: "2026-08-16T15:01:00Z")

    saved = store.save(record, actor="tester")
    loaded = store.get(record.execution_id)

    assert loaded == saved
    assert loaded["execution_id"] == record.execution_id
    assert loaded["sandbox"] is True
    assert loaded["read_only"] is True
    assert loaded["store_schema_version"] == "sandbox-execution-store.v1"
    assert loaded["fingerprint"] == store.fingerprint(record)
    assert "raw_metrics_payload" not in str(loaded)


def test_list_by_playbook_status_and_deterministic_ordering(tmp_path):
    _, _, later = _record(tmp_path, executed_at="2026-08-16T15:02:00Z")
    _, _, earlier = _record(tmp_path, executed_at="2026-08-16T15:00:00Z")
    blocked = replace(earlier, execution_id="sandbox_execution_blocked", status="blocked", blocked_reasons=("blocked",))
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")

    store.save(later)
    store.save(earlier)
    store.save(blocked)

    completed = store.list(playbook_id=earlier.playbook_id, status="completed")

    assert [item["executed_at"] for item in completed] == [
        "2026-08-16T15:00:00Z",
        "2026-08-16T15:02:00Z",
    ]
    assert store.list(status="blocked")[0]["execution_id"] == "sandbox_execution_blocked"


def test_same_semantic_record_different_id_and_timestamp_has_same_fingerprint(tmp_path):
    _, _, first = _record(tmp_path, executed_at="2026-08-16T15:00:00Z")
    second = replace(first, execution_id="sandbox_execution_other", executed_at="2026-08-16T16:00:00Z")
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")

    assert store.fingerprint(first) == store.fingerprint(second)


def test_changed_output_or_blocker_changes_fingerprint_and_compare_codes(tmp_path):
    _, _, first = _record(tmp_path)
    changed_output = replace(
        first,
        step_results=(
            replace(first.step_results[0], output_ref_or_value={"changed": True}),
            first.step_results[1],
        ),
    )
    changed_blocker = replace(first, status="blocked", blocked_reasons=("capability_not_available",))
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")

    output_compare = store.compare(first, changed_output)
    blocker_compare = store.compare(first, changed_blocker)

    assert output_compare["matched"] is False
    assert "output_changed" in output_compare["differences"]
    assert store.fingerprint(first) != store.fingerprint(changed_output)
    assert "status_changed" in blocker_compare["differences"]
    assert "blocker_changed" in blocker_compare["differences"]

