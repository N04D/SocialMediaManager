from __future__ import annotations

from src.core.runtime import ReadOnlyPlaybookSandbox

from tests.test_phase65_read_only_sandbox import _plan


def _without_identity(record: dict) -> dict:
    clone = dict(record)
    clone["execution_id"] = "<execution>"
    clone["executed_at"] = "<executed_at>"
    return clone


def test_same_plan_context_policy_produces_equivalent_results_except_identity_and_time(tmp_path):
    context, plan = _plan(
        tmp_path,
        [
            {"step_id": "z-pubs", "name": "Publications", "kind": "list_publications"},
            {"step_id": "a-context", "name": "Context", "kind": "inspect_context"},
        ],
    )

    first = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T14:01:00Z").execute(plan, context).to_dict()
    second = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T14:02:00Z").execute(plan, context).to_dict()

    assert _without_identity(first) == _without_identity(second)
    assert [item["step_id"] for item in first["step_results"]] == ["a-context", "z-pubs"]
