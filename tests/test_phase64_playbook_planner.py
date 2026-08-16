from __future__ import annotations

from src.core.runtime import PlaybookPlanner, PlaybookRegistry

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def test_explicit_playbook_version_plan_includes_dry_run_step_plans(tmp_path):
    registry = PlaybookRegistry()
    registry.register(
        playbook(
            version="1.0.0",
            provenance={"definition_source": "phase64-fixture", "intent": "content.performance"},
        )
    )
    planner = PlaybookPlanner(registry=registry, clock=lambda: "2026-08-16T13:00:00Z")

    plan = planner.plan_explicit(_context(tmp_path), playbook_id="content.performance.observe", version="1.0.0")
    payload = plan.to_dict()

    assert payload["playbook_id"] == "content.performance.observe"
    assert payload["playbook_version"] == "1.0.0"
    assert payload["dry_run"] is True
    assert payload["executed"] is False
    assert payload["executable"] is True
    assert payload["blocked_reasons"] == []
    assert payload["required_capabilities"] == ["content.performance.context.read"]
    assert payload["step_plans"][0]["status"] == "planned"
    assert payload["step_plans"][0]["allowed_side_effects"] is False
    assert payload["provenance"]["planner_version"] == "playbook-planner.v1"


def test_selected_playbook_by_context_and_intent_uses_registry_selection(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0", provenance={"definition_source": "fixture", "intent": "content.performance"}))
    registry.register(playbook(playbook_id="content.performance.audit", version="1.0.0"))
    planner = PlaybookPlanner(registry=registry, clock=lambda: "2026-08-16T13:00:00Z")

    plan = planner.plan_for_context(_context(tmp_path), intent="content.performance")

    assert plan.playbook_id == "content.performance.audit"
    assert plan.selection_result["selected_by"]["context_schema_version"] == "content-performance-context.v1"
    assert plan.dry_run is True
    assert plan.executed is False


def test_plans_are_deterministic_for_same_inputs_and_clock(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0"))
    context = _context(tmp_path)
    planner = PlaybookPlanner(registry=registry, clock=lambda: "2026-08-16T13:00:00Z")

    first = planner.plan_for_context(context).to_dict()
    second = planner.plan_for_context(context).to_dict()

    assert first == second
