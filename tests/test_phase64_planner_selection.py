from __future__ import annotations

from src.core.runtime import PlaybookPlanner, PlaybookRegistry, PlaybookRegistryStatus, PlaybookSelectionPolicy

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def test_explicit_playbook_id_uses_policy_version_resolution(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0"))
    registry.register(playbook(version="1.2.0"))

    plan = PlaybookPlanner(registry=registry).plan_explicit(_context(tmp_path), playbook_id="content.performance.observe")

    assert plan.playbook_version == "1.2.0"
    assert plan.selection_result["selected_by"]["version_resolution"] == "highest_version"


def test_mutation_playbook_blocked_by_default_but_theoretically_executable_when_allowed(tmp_path):
    registry = PlaybookRegistry()
    registry.register(
        playbook(
            playbook_id="content.performance.publish",
            capability_requirements={"read": ["content.performance.context.read"], "mutations": ["website.article.publish"]},
            mutation_policy={"allowed": True, "allowed_capabilities": ["website.article.publish"]},
        )
    )
    planner = PlaybookPlanner(registry=registry)

    default = planner.plan_explicit(_context(tmp_path), playbook_id="content.performance.publish", version="1.0.0")
    allowed = planner.plan_explicit(
        _context(tmp_path),
        playbook_id="content.performance.publish",
        version="1.0.0",
        policy=PlaybookSelectionPolicy(allow_mutations=True),
    )

    assert default.executable is False
    assert "mutation_not_allowed" in default.blocked_reasons
    assert default.mutation_required is True
    assert "website.article.publish" in default.required_capabilities
    assert allowed.executable is True
    assert allowed.dry_run is True
    assert allowed.executed is False


def test_raw_metrics_playbook_blocked_by_default_and_raw_lookup_not_performed(tmp_path):
    registry = PlaybookRegistry()
    registry.register(
        playbook(
            playbook_id="content.performance.raw",
            raw_access_policy={"raw_metrics": True, "raw_transcript": False, "provider_payloads": True, "secrets": False},
        )
    )
    planner = PlaybookPlanner(registry=registry)

    plan = planner.plan_explicit(_context(tmp_path), playbook_id="content.performance.raw", version="1.0.0")
    allowed = planner.plan_explicit(
        _context(tmp_path),
        playbook_id="content.performance.raw",
        version="1.0.0",
        policy=PlaybookSelectionPolicy(allow_raw_metrics=True),
    )

    assert plan.executable is False
    assert "raw_access_not_allowed" in plan.blocked_reasons
    assert plan.raw_access_required is True
    assert allowed.executable is True
    assert "raw_metrics_payload" not in str(allowed.to_dict())


def test_deprecated_disabled_and_invalid_planning_policy(tmp_path):
    context = _context(tmp_path)
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0", status=PlaybookRegistryStatus.DEPRECATED.value))
    registry.register(playbook(version="1.1.0", status=PlaybookRegistryStatus.DISABLED.value))
    registry.register(playbook(version="1.2.0", status=PlaybookRegistryStatus.INVALID.value))
    planner = PlaybookPlanner(registry=registry)

    deprecated = planner.plan_explicit(context, playbook_id="content.performance.observe", version="1.0.0")
    deprecated_allowed = planner.plan_explicit(
        context,
        playbook_id="content.performance.observe",
        version="1.0.0",
        policy=PlaybookSelectionPolicy(allow_deprecated=True),
    )
    disabled = planner.plan_explicit(context, playbook_id="content.performance.observe", version="1.1.0")
    invalid = planner.plan_explicit(context, playbook_id="content.performance.observe", version="1.2.0")

    assert "deprecated" in deprecated.blocked_reasons
    assert deprecated_allowed.executable is True
    assert "disabled" in disabled.blocked_reasons
    assert "invalid" in invalid.blocked_reasons
