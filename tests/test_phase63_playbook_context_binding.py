from __future__ import annotations

from src.core.runtime import PlaybookRegistry

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def test_context_requirements_match_phase62_context_and_are_resolvable(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(
        playbook(
            context_contract={
                "schema_version": "content-performance-context.v1",
                "requires_transcript": True,
                "requires_publications": True,
                "requires_metrics_history": True,
                "raw_metrics_required": False,
                "raw_transcript_required": False,
            }
        )
    )

    selected = registry.select_for_context(context)
    requirements = registry.resolve_context_requirements("content.performance.observe", "1.0.0")

    assert selected.first is not None
    assert selected.first.playbook_id == "content.performance.observe"
    assert requirements == {
        "raw_metrics_required": False,
        "raw_transcript_required": False,
        "requires_metrics_history": True,
        "requires_publications": True,
        "requires_transcript": True,
        "schema_version": "content-performance-context.v1",
    }


def test_context_requirements_reject_missing_transcript_publication_or_metrics(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_transcript": True}))
    no_transcript = {**context, "transcript_state": {**context["transcript_state"], "available": False}}
    no_publications = {**context, "publications": []}
    no_metrics = {**context, "freshness": {**context["freshness"], "metrics_present": False}, "publications": []}

    assert registry.select_for_context(no_transcript).rejected[0]["reason"] == "transcript_required"

    registry = PlaybookRegistry()
    registry.register(playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_publications": True}))
    assert registry.select_for_context(no_publications).rejected[0]["reason"] == "publication_required"

    registry = PlaybookRegistry()
    registry.register(playbook(context_contract={"schema_version": "content-performance-context.v1", "requires_metrics_history": True}))
    assert registry.select_for_context(no_metrics).rejected[0]["reason"] == "metrics_required"


def test_playbook_context_binding_does_not_include_raw_payloads_by_default(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook())

    selected = registry.select_for_context(context)

    assert selected.first is not None
    assert context["redaction"]["raw_metrics_included"] is False
    assert context["redaction"]["raw_transcript_included"] is False
    assert "raw_metrics_payload" not in str(context)
    assert selected.first.raw_access_policy.raw_metrics is False
    assert selected.first.raw_access_policy.raw_transcript is False
