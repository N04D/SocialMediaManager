from __future__ import annotations

from src.core.runtime import PlaybookPlanner, PlaybookRegistry

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def test_missing_transcript_publication_metrics_and_schema_create_non_executable_plans(tmp_path):
    context = _context(tmp_path)

    transcript_registry = PlaybookRegistry()
    transcript_registry.register(
        playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_transcript": True})
    )
    transcript_plan = PlaybookPlanner(registry=transcript_registry).plan_explicit(
        {**context, "transcript_state": {**context["transcript_state"], "available": False}},
        playbook_id="content.performance.observe",
        version="1.0.0",
    )

    publication_registry = PlaybookRegistry()
    publication_registry.register(
        playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_publications": True})
    )
    publication_plan = PlaybookPlanner(registry=publication_registry).plan_explicit(
        {**context, "publications": []},
        playbook_id="content.performance.observe",
        version="1.0.0",
    )

    metrics_registry = PlaybookRegistry()
    metrics_registry.register(
        playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_metrics_history": True})
    )
    metrics_plan = PlaybookPlanner(registry=metrics_registry).plan_explicit(
        {**context, "freshness": {**context["freshness"], "metrics_present": False}, "publications": []},
        playbook_id="content.performance.observe",
        version="1.0.0",
    )

    schema_plan = PlaybookPlanner(registry=metrics_registry).plan_explicit(
        {**context, "schema_version": "wrong.v1"},
        playbook_id="content.performance.observe",
        version="1.0.0",
    )

    assert transcript_plan.executable is False
    assert "transcript_required" in transcript_plan.blocked_reasons
    assert publication_plan.executable is False
    assert "publication_required" in publication_plan.blocked_reasons
    assert metrics_plan.executable is False
    assert "metrics_required" in metrics_plan.blocked_reasons
    assert schema_plan.executable is False
    assert "context_schema_mismatch" in schema_plan.blocked_reasons


def test_missing_required_capability_blocks_but_keeps_plan_metadata(tmp_path):
    registry = PlaybookRegistry()
    registry.register(
        playbook(
            capability_requirements={
                "read": ["content.performance.context.read", "content.performance.future.read"],
                "optional": [],
                "mutations": [],
            }
        )
    )
    planner = PlaybookPlanner(registry=registry)

    plan = planner.plan_explicit(_context(tmp_path), playbook_id="content.performance.observe", version="1.0.0")

    assert plan.executable is False
    assert "capability_not_available" in plan.blocked_reasons
    assert "content.performance.future.read" in plan.required_capabilities
    assert plan.step_plans[0].status == "blocked"


def test_no_selected_playbook_returns_structured_blocked_plan(tmp_path):
    registry = PlaybookRegistry()
    planner = PlaybookPlanner(registry=registry)

    plan = planner.plan_for_context(_context(tmp_path))

    assert plan.executable is False
    assert plan.playbook_id == ""
    assert "playbook_not_selected" in plan.blocked_reasons
    assert plan.dry_run is True
    assert plan.executed is False
