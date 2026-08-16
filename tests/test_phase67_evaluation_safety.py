from __future__ import annotations

from pathlib import Path

from src.core.runtime import SandboxEvaluationHarness, SandboxExecutionStore
from src.core.runtime.capabilities import CapabilityMode
from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs

from tests.test_phase66_sandbox_execution_store import _record


def _saved_payload(tmp_path):
    _, _, record = _record(tmp_path)
    return SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)


def test_secret_and_authorization_canaries_do_not_leak_into_result(tmp_path):
    payload = _saved_payload(tmp_path)
    poisoned = {
        **payload,
        "provenance": {
            **payload["provenance"],
            "note": "SECRET_CANARY Authorization: Bearer token",
        },
    }

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(poisoned)
    rendered = str(result.to_dict())

    assert result.status == "failed"
    assert "forbidden_data_present" in result.failures
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer " not in rendered


def test_raw_payload_names_do_not_leak_into_result(tmp_path):
    payload = _saved_payload(tmp_path)
    poisoned = {**payload, "raw_metrics_payload": {"views": 100}, "raw_transcript_body": "hello"}

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(poisoned)
    rendered = str(result.to_dict())

    assert result.status == "failed"
    assert "forbidden_data_present" in result.failures
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_evaluation_does_not_invoke_executor_or_raw_lookup(tmp_path, monkeypatch):
    payload = _saved_payload(tmp_path)
    invoked = {"executor": False, "raw": False}

    def forbidden_executor(*args, **kwargs):
        invoked["executor"] = True
        raise AssertionError("production executor must not be invoked")

    def forbidden_raw(*args, **kwargs):
        invoked["raw"] = True
        raise AssertionError("raw lookup must not be invoked")

    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", forbidden_executor)
    monkeypatch.setattr(
        "src.core.content.performance_context.ContentPerformanceContextService.get_raw_metrics_snapshot",
        forbidden_raw,
    )

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload)

    assert result.status == "passed"
    assert invoked == {"executor": False, "raw": False}


def test_harness_source_has_no_ai_browser_scraping_or_network_path():
    source = Path("src/core/runtime/sandbox_evaluation.py").read_text(encoding="utf-8").lower()

    forbidden = [
        "playbookexecutor",
        "openai",
        "anthropic",
        "chatgpt",
        "requests.",
        "subprocess",
        "browser",
        "scrap",
        "youtube.metrics.read",
        "youtube.analytics.read",
    ]
    assert not any(item in source for item in forbidden)


def test_production_boundaries_remain_unchanged():
    production_write_capabilities = sorted(
        capability.capability_id
        for manifest in phase41_component_manifests()
        for capability in manifest.capabilities
        if capability.mode == CapabilityMode.WRITE.value
        and capability.capability_id in {"calendar.event.create", "website.article.publish"}
    )
    youtube_metrics = [
        capability
        for install in phase41_sample_installs()
        if install.provider == "youtube"
        for capability in install.component_bindings
        if capability in {"youtube.metrics.read", "youtube.analytics.read"}
    ]

    assert production_write_capabilities == ["calendar.event.create", "website.article.publish"]
    assert youtube_metrics == []

