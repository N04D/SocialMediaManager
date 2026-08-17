from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import ExecutionEligibilityGate
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase72_execution_eligibility_gate import _eligible_bundle


def test_no_approval_mutation_or_runtime_paths(tmp_path, monkeypatch):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    invoked = {"approve": False, "executor": False, "sandbox": False, "replay": False, "evaluation": False, "promotion": False}

    def forbidden(name):
        def inner(*args, **kwargs):
            invoked[name] = True
            raise AssertionError(f"{name} must not be invoked")

        return inner

    monkeypatch.setattr("src.core.runtime.approval_state_machine.ApprovalStore.approve", forbidden("approve"))
    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", forbidden("executor"))
    monkeypatch.setattr("src.core.runtime.playbook_sandbox.ReadOnlyPlaybookSandbox.execute", forbidden("sandbox"))
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", forbidden("replay"))
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", forbidden("evaluation"))
    monkeypatch.setattr("src.core.runtime.promotion_gate.PromotionGate.decide", forbidden("promotion"))

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "eligible"
    assert invoked == {"approve": False, "executor": False, "sandbox": False, "replay": False, "evaluation": False, "promotion": False}


def test_no_raw_payload_or_secret_leakage(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    unsafe_approval = approval.to_dict()
    unsafe_approval["unsafe_extra"] = {
        "raw_metrics_payload": {"views": 1},
        "raw_transcript_body": "SECRET_CANARY Authorization Bearer provider_headers",
    }

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        unsafe_approval,
        plan=plan,
        execution_record=execution,
    )
    rendered = str(decision.to_dict())

    assert decision.status == "blocked"
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_unsafe_action_kind_blocks(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    unsafe = approval.to_dict()
    unsafe["requested_action_kind"] = "publish"

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        unsafe,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "blocked"
    assert "unsafe_action_kind" in [reason.reason_code for reason in decision.reasons]


def test_forbidden_execution_markers_block(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    marked = {**execution, "provenance": {"production_executor_invoked": True, "ai_invoked": True}}

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=marked,
    )

    assert decision.status == "blocked"
    assert "forbidden_execution_marker" in [reason.reason_code for reason in decision.reasons]


def test_gate_source_has_no_ai_interactive_collection_or_network_path():
    source = Path("src/core/runtime/execution_eligibility_gate.py").read_text(encoding="utf-8").lower()

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
