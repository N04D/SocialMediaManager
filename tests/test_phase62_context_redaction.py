from __future__ import annotations

import json
import inspect

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase62_content_performance_context import _build_context_fixture


def test_context_redaction_omits_raw_payloads_transcript_body_and_credentials(tmp_path):
    item, service, _ = _build_context_fixture(tmp_path)

    payload = service.get_context(item.id).to_dict()
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["redaction"] == {
        "provider_headers_included": False,
        "raw_metrics_included": False,
        "raw_transcript_included": False,
        "secrets_included": False,
    }
    assert "raw_metrics_payload" not in rendered
    assert "raw transcript" not in rendered.lower()
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer " not in rendered


def test_context_boundary_tripwires_remain_read_only_and_provider_neutral():
    manifests = phase41_component_manifests()
    production_write_capabilities = sorted(
        capability.capability_id
        for manifest in manifests
        for capability in manifest.capabilities
        if capability.mode == CapabilityMode.WRITE.value
        and capability.capability_id in {"calendar.event.create", "website.article.publish"}
    )
    youtube_metric_bindings = [
        binding
        for install in phase41_sample_installs()
        if install.provider == "youtube"
        for capability, binding in install.component_bindings.items()
        if capability in {"youtube.metrics.read", "youtube.analytics.read"}
    ]

    import src.core.content.performance_context as performance_context

    source = inspect.getsource(performance_context)
    assert production_write_capabilities == ["calendar.event.create", "website.article.publish"]
    assert youtube_metric_bindings == []
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()
    assert 'if provider == "youtube"' not in source
    assert 'if publication.provider == "youtube"' not in source
