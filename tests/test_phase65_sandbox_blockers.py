from __future__ import annotations

from src.core.runtime import PlaybookPlanner, PlaybookRegistry, PlaybookSelectionPolicy, ReadOnlyPlaybookSandbox

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook
from tests.test_phase65_read_only_sandbox import _plan, _registry_with_steps


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def test_non_executable_plan_blocks_without_step_execution(tmp_path):
    context = _context(tmp_path)
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
    plan = PlaybookPlanner(registry=registry).plan_explicit(
        context,
        playbook_id="content.performance.observe",
        version="1.0.0",
    )

    record = ReadOnlyPlaybookSandbox().execute(plan, context)

    assert record.status == "blocked"
    assert record.step_results == ()
    assert "capability_not_available" in record.blocked_reasons


def test_unsupported_step_kind_blocks_fail_closed(tmp_path):
    context, plan = _plan(tmp_path, [{"step_id": "unknown", "name": "Unknown", "kind": "do_unknown"}])

    record = ReadOnlyPlaybookSandbox().execute(plan, context)

    assert record.status == "blocked"
    assert record.step_results[0].status == "blocked"
    assert record.step_results[0].blocked_reasons == ("unsupported_step_kind",)


def test_missing_step_capability_blocks_step(tmp_path):
    context, plan = _plan(
        tmp_path,
        [
            {
                "step_id": "future",
                "name": "Future",
                "kind": "inspect_context",
                "required_capabilities": ["content.performance.future.read"],
            }
        ],
    )

    record = ReadOnlyPlaybookSandbox().execute(plan, context)

    assert record.status == "blocked"
    assert "capability_not_available" in record.step_results[0].blocked_reasons


def test_raw_required_step_blocks_by_default_even_when_plan_exists(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "raw", "name": "Raw", "kind": "inspect_context", "raw_access_required": True}],
    )

    record = ReadOnlyPlaybookSandbox().execute(plan, context)

    assert record.status == "blocked"
    assert "raw_access_not_allowed" in record.step_results[0].blocked_reasons
    assert record.step_results[0].raw_access_used is False


def test_mutation_required_step_blocks_even_when_policy_allows_mutations(tmp_path):
    context = _context(tmp_path)
    registry = _registry_with_steps(
        [{"step_id": "mutate", "name": "Mutate", "kind": "inspect_context", "mutation_required": True}]
    )
    plan = PlaybookPlanner(registry=registry).plan_explicit(
        context,
        playbook_id="content.performance.observe",
        version="1.0.0",
        policy=PlaybookSelectionPolicy(allow_mutations=True),
    )

    record = ReadOnlyPlaybookSandbox().execute(plan, context, policy=PlaybookSelectionPolicy(allow_mutations=True))

    assert record.status == "blocked"
    assert "mutation_not_allowed" in record.step_results[0].blocked_reasons
    assert record.step_results[0].mutation_used is False
