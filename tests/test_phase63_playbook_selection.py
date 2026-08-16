from __future__ import annotations

from src.core.runtime import (
    PlaybookRegistry,
    PlaybookRegistryStatus,
    PlaybookSelectionPolicy,
)

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def _context(tmp_path) -> dict:
    item, service, _ = _build_context_fixture(tmp_path)
    return service.get_context(item.id).to_dict()


def test_selection_is_deterministic_and_uses_highest_compatible_version(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0"))
    registry.register(playbook(version="1.2.0"))
    registry.register(playbook(version="1.1.0"))
    registry.register(playbook(playbook_id="content.performance.audit", version="1.0.0"))

    result = registry.select_for_context(_context(tmp_path))

    assert [(item.playbook_id, item.version) for item in result.selected] == [
        ("content.performance.audit", "1.0.0"),
        ("content.performance.observe", "1.2.0"),
    ]
    assert result.first.playbook_id == "content.performance.audit"
    assert result.selected_by["context_schema_version"] == "content-performance-context.v1"


def test_disabled_invalid_and_deprecated_are_not_selected_by_default(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0", status=PlaybookRegistryStatus.DEPRECATED.value))
    registry.register(playbook(version="1.1.0", status=PlaybookRegistryStatus.DISABLED.value))
    registry.register(playbook(version="1.2.0", status=PlaybookRegistryStatus.INVALID.value))

    result = registry.select_for_context(_context(tmp_path))

    assert result.selected == ()
    assert {item["reason"] for item in result.rejected} == {"deprecated", "disabled", "invalid"}


def test_deprecated_selected_only_when_policy_allows_it(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0", status=PlaybookRegistryStatus.DEPRECATED.value))

    default = registry.select_for_context(_context(tmp_path))
    allowed = registry.select_for_context(_context(tmp_path), policy=PlaybookSelectionPolicy(allow_deprecated=True))

    assert default.selected == ()
    assert [item.version for item in allowed.selected] == ["1.0.0"]


def test_raw_and_mutation_playbooks_require_explicit_selection_policy(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0"))
    registry.register(
        playbook(
            playbook_id="content.performance.raw",
            raw_access_policy={"raw_metrics": True, "raw_transcript": False, "provider_payloads": True, "secrets": False},
        )
    )
    registry.register(
        playbook(
            playbook_id="content.performance.mutate",
            capability_requirements={"read": ["content.performance.context.read"], "mutations": ["website.article.publish"]},
            mutation_policy={"allowed": True, "allowed_capabilities": ["website.article.publish"]},
        )
    )

    default = registry.select_for_context(_context(tmp_path))
    expanded = registry.select_for_context(
        _context(tmp_path),
        policy=PlaybookSelectionPolicy(allow_raw_metrics=True, allow_mutations=True),
    )

    assert [item.playbook_id for item in default.selected] == ["content.performance.observe"]
    assert {item["reason"] for item in default.rejected} >= {"raw_metrics_not_allowed", "mutation_not_allowed"}
    assert [item.playbook_id for item in expanded.selected] == [
        "content.performance.mutate",
        "content.performance.observe",
        "content.performance.raw",
    ]


def test_select_all_versions_when_latest_policy_is_disabled(tmp_path):
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0"))
    registry.register(playbook(version="1.1.0"))

    result = registry.select_for_context(
        _context(tmp_path),
        policy=PlaybookSelectionPolicy(select_highest_version=False),
    )

    assert [item.version for item in result.selected] == ["1.0.0", "1.1.0"]
