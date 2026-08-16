from __future__ import annotations

from src.core.runtime import ReadOnlyPlaybookSandbox, SandboxExecutionStore, SandboxReplayService

from tests.test_phase65_read_only_sandbox import _plan


def _saved_execution(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}],
    )
    sandbox = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:00:00Z")
    record = sandbox.execute(plan, context)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json", clock=lambda: "2026-08-16T15:01:00Z")
    store.save(record)
    return context, plan, record, store


def test_explicit_replay_produces_matching_replay_result_without_auto_save(tmp_path):
    context, plan, record, store = _saved_execution(tmp_path)
    replay = SandboxReplayService(
        store=store,
        sandbox=ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T16:00:00Z"),
        clock=lambda: "2026-08-16T16:01:00Z",
    )

    result = replay.replay(record.execution_id, context, plan=plan)

    assert result.status == "completed"
    assert result.matched is True
    assert result.original_execution_id == record.execution_id
    assert result.replay_execution_id != ""
    assert result.differences == ()
    assert len(store.list()) == 1
    assert [item["event_type"] for item in store.audit_events()] == ["saved"]


def test_changed_context_result_differs(tmp_path):
    context, plan, record, store = _saved_execution(tmp_path)
    changed_context = {
        **context,
        "publications": [],
        "freshness": {**context["freshness"], "metrics_present": False},
    }

    result = SandboxReplayService(
        store=store,
        sandbox=ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T16:00:00Z"),
    ).compare_replay(record.execution_id, changed_context, plan=plan)

    assert result.matched is False
    assert "output_changed" in result.differences


def test_missing_context_or_plan_blocks_without_exception(tmp_path):
    context, plan, record, store = _saved_execution(tmp_path)
    replay = SandboxReplayService(store=store)

    no_context = replay.replay(record.execution_id, None, plan=plan)
    no_plan = replay.replay(record.execution_id, context)
    missing_record = replay.replay("missing", context, plan=plan)

    assert no_context.status == "blocked"
    assert no_context.differences == ("missing_context",)
    assert no_plan.status == "blocked"
    assert no_plan.differences == ("missing_plan",)
    assert missing_record.differences == ("missing_execution",)


def test_replay_save_is_explicit_and_audited(tmp_path):
    context, plan, record, store = _saved_execution(tmp_path)

    result = SandboxReplayService(
        store=store,
        sandbox=ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T16:00:00Z"),
    ).replay(record.execution_id, context, plan=plan, save_replay=True)

    events = store.audit_events()
    assert result.matched is True
    assert len(store.list()) == 2
    assert [item["event_type"] for item in events] == ["saved", "saved", "replay_result_saved"]
    assert events[-1]["payload"]["original_execution_id"] == record.execution_id

