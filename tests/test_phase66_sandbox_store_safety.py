from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.core.runtime import ReadOnlyPlaybookSandbox, SandboxExecutionStore, SandboxReplayService
from src.core.runtime.capabilities import CapabilityMode
from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs

from tests.test_phase65_read_only_sandbox import _plan


def test_persisted_record_excludes_raw_payloads_headers_and_secrets(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}],
    )
    record = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:00:00Z").execute(plan, context)
    store_path = tmp_path / "sandbox-executions.json"
    store = SandboxExecutionStore(store_path, clock=lambda: "2026-08-16T15:01:00Z")

    store.save(record, actor="SECRET_CANARY_ACTOR")
    rendered = store_path.read_text(encoding="utf-8")

    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer " not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered
    assert "redacted" in rendered


def test_store_and_replay_do_not_invoke_production_executor_or_raw_lookup(tmp_path, monkeypatch):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "inspect", "name": "Inspect", "kind": "inspect_context"}],
    )
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    record = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T15:00:00Z").execute(plan, context)
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

    store.save(record)
    SandboxReplayService(
        store=store,
        sandbox=ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T16:00:00Z"),
    ).replay(record.execution_id, context, plan=plan)

    assert invoked == {"executor": False, "raw": False}


def test_store_source_has_no_ai_browser_scraping_or_network_path():
    source = Path("src/core/runtime/sandbox_execution_store.py").read_text(encoding="utf-8").lower()

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
