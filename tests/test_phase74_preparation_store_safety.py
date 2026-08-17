from __future__ import annotations

from pathlib import Path

import pytest

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import ExecutionPreparationStore
from src.core.runtime.capabilities import CapabilityMode
from src.core.runtime.errors import PlaybookValidationError

from tests.test_phase74_preparation_store import _record


def test_save_does_not_invoke_execution_approval_or_network_layers(monkeypatch, tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json")
    calls: list[str] = []

    def marker(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("side-effect path invoked")

    monkeypatch.setattr("src.core.runtime.playbook_sandbox.ReadOnlyPlaybookSandbox.execute", marker)
    monkeypatch.setattr("src.core.runtime.approval_state_machine.ApprovalStore.approve", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", marker)

    saved = store.save(record)

    assert saved["status"] == "ready"
    assert calls == []


def test_store_rejects_raw_secret_payloads(tmp_path):
    record = _record(tmp_path)
    unsafe = {
        **record.to_dict(),
        "provenance": {
            "Authorization": "Bearer token",
            "raw_transcript_body": "text",
            "raw_metrics_payload": {"views": 1},
            "secret": "SECRET_CANARY",
        },
    }
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    with pytest.raises(PlaybookValidationError):
        store.save(unsafe)


def test_no_claim_executing_or_executed_status_is_supported(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    for status in ("claimed", "executing", "executed"):
        with pytest.raises(PlaybookValidationError):
            store.save({**record.to_dict(), "status": status})


def test_persisted_record_has_safe_redaction_flags(tmp_path):
    record = _record(tmp_path)
    store = ExecutionPreparationStore(tmp_path / "preparations.json")

    saved = store.save(record)

    assert saved["redaction"]["raw_metrics_included"] is False
    assert saved["redaction"]["raw_transcript_included"] is False
    assert saved["redaction"]["secrets_included"] is False
    assert saved["redaction"]["provider_headers_included"] is False
    assert saved["redaction"]["approval_state_mutated"] is False
    assert saved["redaction"]["execution_started"] is False
    assert saved["redaction"]["production_mutation_used"] is False


def test_production_boundaries_remain_unchanged():
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


def test_store_source_has_no_execution_ai_network_or_provider_metric_reader_references():
    source = Path("src/core/runtime/execution_preparation_store.py").read_text(encoding="utf-8").lower()

    for forbidden in (
        "playbookexecutor",
        "openai",
        "anthropic",
        "chatgpt",
        "requests.",
        "subprocess",
        "youtube.metrics.read",
        "youtube.analytics.read",
    ):
        assert forbidden not in source
