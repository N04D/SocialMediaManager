from __future__ import annotations

from src.core.runtime import PlaybookPlanner, PlaybookRegistry, ReadOnlyPlaybookSandbox

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def _registry_with_steps(steps: list[dict]) -> PlaybookRegistry:
    registry = PlaybookRegistry()
    definition = playbook()
    registry.register(
        definition.__class__(
            **{
                **definition.__dict__,
                "steps": tuple(steps),
            }
        )
    )
    return registry


def _plan(tmp_path, steps: list[dict]):
    context = _context(tmp_path)
    registry = _registry_with_steps(steps)
    planner = PlaybookPlanner(registry=registry, clock=lambda: "2026-08-16T14:00:00Z")
    return context, planner.plan_explicit(context, playbook_id="content.performance.observe", version="1.0.0")


def test_executable_plan_produces_sandbox_execution_record_and_step_results(tmp_path):
    context, plan = _plan(
        tmp_path,
        [
            {"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"},
            {"step_id": "transcript", "name": "Transcript", "kind": "check_transcript_available"},
            {"step_id": "metrics", "name": "Metrics", "kind": "check_metrics_available"},
        ],
    )
    sandbox = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T14:01:00Z")

    record = sandbox.execute(plan, context)
    payload = record.to_dict()

    assert payload["sandbox"] is True
    assert payload["read_only"] is True
    assert payload["status"] == "completed"
    assert payload["dry_run_source_plan"] == {
        "dry_run": True,
        "executed": False,
        "plan_id": plan.plan_id,
        "schema_version": "playbook-plan.v1",
    }
    assert [item["step_id"] for item in payload["step_results"]] == ["inspect", "metrics", "transcript"]
    assert all(item["mutation_used"] is False for item in payload["step_results"])
    assert all(item["raw_access_used"] is False for item in payload["step_results"])
    assert payload["redaction"]["mutations_used"] is False
    assert payload["redaction"]["raw_metrics_included"] is False


def test_list_publications_and_metric_history_are_read_only_and_deterministic(tmp_path):
    context, plan = _plan(
        tmp_path,
        [
            {"step_id": "pubs", "name": "Publications", "kind": "list_publications"},
            {"step_id": "history", "name": "History", "kind": "list_metric_history"},
            {"step_id": "fields", "name": "Fields", "kind": "summarize_available_fields"},
        ],
    )

    first = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T14:01:00Z").execute(plan, context).to_dict()
    second = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T14:01:00Z").execute(plan, context).to_dict()

    assert first == second
    history = [item for item in first["step_results"] if item["step_id"] == "history"][0]
    assert len(history["output_ref_or_value"]["metrics"]) == 4
    assert history["output_ref_or_value"]["metrics"][0]["metric_keys"] == ["likes", "views"]
    fields = [item for item in first["step_results"] if item["step_id"] == "fields"][0]
    assert "publications" in fields["output_ref_or_value"]["available_fields"]
