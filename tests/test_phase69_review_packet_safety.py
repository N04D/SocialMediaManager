from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import ManualReviewPacketBuilder
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase69_manual_review_packet import _eligible_subject


def test_no_secret_authorization_or_raw_payload_in_packet(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    unsafe_execution = {
        **execution,
        "raw_metrics_payload": {"views": 100},
        "raw_transcript_body": "hello",
        "provenance": {"note": "SECRET_CANARY Authorization Bearer provider_headers"},
    }

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=unsafe_execution,
        plan=plan,
    )
    rendered = str(packet.to_dict())

    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered
    assert "note" not in rendered


def test_packet_redaction_flags_default_false(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert packet.redaction.raw_metrics_included is False
    assert packet.redaction.raw_transcript_included is False
    assert packet.redaction.secrets_included is False
    assert packet.redaction.provider_headers_included is False
    assert packet.redaction.full_step_outputs_included is False


def test_builder_does_not_invoke_execution_replay_evaluation_promotion_or_raw_lookup(tmp_path, monkeypatch):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    invoked = {"executor": False, "replay": False, "evaluation": False, "promotion": False, "raw": False}

    def forbidden(name):
        def inner(*args, **kwargs):
            invoked[name] = True
            raise AssertionError(f"{name} must not be invoked")

        return inner

    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", forbidden("executor"))
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", forbidden("replay"))
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", forbidden("evaluation"))
    monkeypatch.setattr("src.core.runtime.promotion_gate.PromotionGate.decide", forbidden("promotion"))
    monkeypatch.setattr(
        "src.core.content.performance_context.ContentPerformanceContextService.get_raw_metrics_snapshot",
        forbidden("raw"),
    )

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert packet.status == "informational"
    assert invoked == {"executor": False, "replay": False, "evaluation": False, "promotion": False, "raw": False}


def test_builder_source_has_no_ai_browser_scraping_or_network_path():
    source = Path("src/core/runtime/manual_review_packet.py").read_text(encoding="utf-8").lower()

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
