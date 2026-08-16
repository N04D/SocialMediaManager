from __future__ import annotations

import inspect
import json

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import PlaybookPlanner, PlaybookRegistry, ReadOnlyPlaybookSandbox
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook
from tests.test_phase65_read_only_sandbox import _registry_with_steps


def test_sandbox_does_not_invoke_production_executor_or_raw_lookup(tmp_path, monkeypatch):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = _registry_with_steps([{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}])
    plan = PlaybookPlanner(registry=registry).plan_explicit(
        context, playbook_id="content.performance.observe", version="1.0.0"
    )

    def fail_executor(*args, **kwargs):
        raise AssertionError("production executor must not be invoked")

    def fail_raw_lookup(*args, **kwargs):
        raise AssertionError("raw lookup must not be invoked")

    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", fail_executor)
    monkeypatch.setattr(service, "get_raw_metrics_snapshot", fail_raw_lookup)

    record = ReadOnlyPlaybookSandbox().execute(plan, context)

    assert record.status == "completed"
    assert record.sandbox is True
    assert record.read_only is True


def test_sandbox_execution_record_contains_no_raw_payloads_transcript_body_or_secrets(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook())
    plan = PlaybookPlanner(registry=registry).plan_explicit(
        context, playbook_id="content.performance.observe", version="1.0.0"
    )

    payload = json.dumps(ReadOnlyPlaybookSandbox().execute(plan, context).to_dict(), sort_keys=True)

    assert "SECRET_CANARY" not in payload
    assert "raw_metrics_payload" not in payload
    assert "raw transcript" not in payload.lower()
    assert "Authorization" not in payload
    assert "Bearer " not in payload


def test_sandbox_core_has_no_ai_network_browser_or_provider_branches():
    import src.core.runtime.playbook_sandbox as playbook_sandbox

    source = inspect.getsource(playbook_sandbox)

    assert "PlaybookExecutor" not in source
    assert ".execute(" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()
    assert "requests." not in source
    assert "subprocess" not in source
    assert "browser" not in source.lower()
    assert "scrap" not in source.lower()
    assert 'if provider == "youtube"' not in source
    assert "youtube.metrics.read" not in source


def test_phase65_does_not_increase_production_boundaries_or_admit_youtube_metrics():
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
