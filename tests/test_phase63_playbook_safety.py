from __future__ import annotations

import inspect
import json

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime.capabilities import CapabilityMode
from src.core.runtime.playbook_registry import PlaybookRegistry

from tests.test_phase62_content_performance_context import _build_context_fixture
from tests.test_phase63_playbook_registry import playbook


def test_playbook_definition_output_contains_no_secrets_or_raw_context(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)
    context = service.get_context(item.id).to_dict()
    registry = PlaybookRegistry()
    registry.register(playbook())

    payload = json.dumps(registry.select_for_context(context).first.to_dict(), sort_keys=True)

    assert "SECRET_CANARY" not in payload
    assert "raw_metrics_payload" not in payload
    assert "raw transcript" not in payload.lower()
    assert "Bearer " not in payload
    assert "Authorization" not in payload


def test_phase63_does_not_increase_production_boundaries_or_admit_youtube_metrics():
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


def test_registry_core_has_no_execution_ai_network_or_provider_branches():
    import src.core.runtime.playbook_registry as playbook_registry

    source = inspect.getsource(playbook_registry)

    assert "PlaybookExecutor" not in source
    assert ".execute(" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()
    assert "requests." not in source
    assert "subprocess" not in source
    assert 'if provider == "youtube"' not in source
    assert 'if definition.provider == "youtube"' not in source
