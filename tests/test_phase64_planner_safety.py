from __future__ import annotations

import inspect
import json

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import PlaybookPlanner, PlaybookRegistry
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def test_planner_never_invokes_executor_or_raw_snapshot_lookup(tmp_path, monkeypatch):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook())
    planner = PlaybookPlanner(registry=registry)

    def fail_executor(*args, **kwargs):
        raise AssertionError("executor must not be invoked")

    def fail_raw_lookup(*args, **kwargs):
        raise AssertionError("raw lookup must not be invoked")

    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", fail_executor)
    monkeypatch.setattr(service, "get_raw_metrics_snapshot", fail_raw_lookup)

    plan = planner.plan_for_context(context)

    assert plan.dry_run is True
    assert plan.executed is False
    assert plan.executable is True


def test_plan_contains_no_raw_payloads_transcript_body_or_secrets(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook())

    payload = json.dumps(PlaybookPlanner(registry=registry).plan_for_context(context).to_dict(), sort_keys=True)

    assert "SECRET_CANARY" not in payload
    assert "raw_metrics_payload" not in payload
    assert "raw transcript" not in payload.lower()
    assert "Authorization" not in payload
    assert "Bearer " not in payload


def test_planner_core_has_no_ai_network_provider_or_execution_branches():
    import src.core.runtime.playbook_planner as playbook_planner

    source = inspect.getsource(playbook_planner)

    assert "PlaybookExecutor" not in source
    assert ".execute(" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()
    assert "requests." not in source
    assert "subprocess" not in source
    assert 'if provider == "youtube"' not in source
    assert 'youtube.metrics.read' not in source


def test_phase64_does_not_increase_production_boundaries_or_admit_youtube_metrics():
    production_write_capabilities = sorted(
        capability.capability_id
        for manifest in phase41_component_manifests()
        for capability in manifest.capabilities
        if capability.mode == CapabilityMode.WRITE.value
        and capability.capability_id in {"calendar.event.create", "website.article.publish"}
    )
    youtube_metric_bindings = [
        capability
        for install in phase41_sample_installs()
        if install.provider == "youtube"
        for capability in install.component_bindings
        if capability in {"youtube.metrics.read", "youtube.analytics.read"}
    ]

    assert production_write_capabilities == ["calendar.event.create", "website.article.publish"]
    assert youtube_metric_bindings == []
