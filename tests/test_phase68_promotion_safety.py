from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import PromotionGate, SandboxEvaluationHarness, SandboxExecutionStore
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase66_sandbox_execution_store import _record


def _subject(tmp_path):
    _, _, record = _record(tmp_path)
    execution = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(execution)
    return execution, evaluation


def test_mutation_and_raw_access_block_by_default(tmp_path):
    execution, evaluation = _subject(tmp_path)
    step = {**execution["step_results"][0], "mutation_used": True, "raw_access_used": True}

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={**execution, "step_results": [step, *execution["step_results"][1:]]},
    )

    assert decision.status == "blocked"
    assert "mutation_used" in PromotionGate().explain(decision)
    assert "raw_access_used" in PromotionGate().explain(decision)


def test_secret_redaction_and_runtime_markers_block(tmp_path):
    execution, evaluation = _subject(tmp_path)
    unsafe_execution = {
        **execution,
        "redaction": {**execution["redaction"], "secrets_included": True},
        "provenance": {
            **execution["provenance"],
            "runtime_marker": "production_executor_invoked ai_invoked interactive_collection_invoked",
        },
    }

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record=unsafe_execution,
    )

    reasons = PromotionGate().explain(decision)
    assert decision.status == "blocked"
    assert "secrets_included" in reasons
    assert "production_executor_invoked" in reasons
    assert "ai_invoked" in reasons
    assert "interactive_collection_invoked" in reasons


def test_no_canaries_or_raw_payloads_in_decision(tmp_path):
    execution, evaluation = _subject(tmp_path)
    unsafe_evaluation = {
        **evaluation.to_dict(),
        "provenance": {
            **evaluation.provenance,
            "note": "SECRET_CANARY Authorization Bearer raw_metrics_payload raw_transcript_body",
        },
    }

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(unsafe_evaluation, execution_record=execution)
    rendered = str(decision.to_dict())

    assert decision.status == "blocked"
    assert "unsafe_evaluation_payload" in PromotionGate().explain(decision)
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_unsafe_next_actions_are_not_emitted(tmp_path):
    execution, evaluation = _subject(tmp_path)

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(evaluation, execution_record=execution)

    rendered = " ".join(decision.eligible_next_actions)
    assert "execute_production" not in rendered
    assert "publish" not in rendered
    assert "mutate" not in rendered
    assert "send" not in rendered
    assert "call_ai" not in rendered


def test_gate_does_not_invoke_execution_replay_evaluation_or_raw_lookup(tmp_path, monkeypatch):
    execution, evaluation = _subject(tmp_path)
    invoked = {"executor": False, "replay": False, "evaluation": False, "raw": False}

    def forbidden(name):
        def inner(*args, **kwargs):
            invoked[name] = True
            raise AssertionError(f"{name} must not be invoked")

        return inner

    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", forbidden("executor"))
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", forbidden("replay"))
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", forbidden("evaluation"))
    monkeypatch.setattr(
        "src.core.content.performance_context.ContentPerformanceContextService.get_raw_metrics_snapshot",
        forbidden("raw"),
    )

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(evaluation, execution_record=execution)

    assert decision.status == "eligible"
    assert invoked == {"executor": False, "replay": False, "evaluation": False, "raw": False}


def test_gate_source_has_no_ai_browser_scraping_or_network_path():
    source = Path("src/core/runtime/promotion_gate.py").read_text(encoding="utf-8").lower()

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

