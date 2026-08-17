from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import ApprovalRequestDraftBuilder, ManualReviewPacketBuilder
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase69_manual_review_packet import _needs_review_subject


def _ready_packet(tmp_path):
    execution, evaluation, decision, plan = _needs_review_subject(tmp_path)
    return ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )


def test_unsafe_action_is_omitted(tmp_path):
    packet = _ready_packet(tmp_path).to_dict()
    packet["safe_next_actions"] = list(packet["safe_next_actions"]) + ["publish"]

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "publish")
    rendered = str(draft.to_dict())

    assert draft.status == "not_requestable"
    assert draft.requested_action_kind == "unsupported"
    assert "unsafe_action_omitted" in [reason.reason_code for reason in draft.reason_codes]
    assert "publish" not in rendered


def test_unsafe_redaction_blocks_or_is_not_requestable(tmp_path):
    packet = _ready_packet(tmp_path).to_dict()
    packet["redaction"]["secrets_included"] = True

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")

    assert draft.status == "blocked"
    assert "unsafe_redaction" in [reason.reason_code for reason in draft.reason_codes]


def test_approval_state_is_not_mutated_and_no_raw_or_secret_payload_leaks(tmp_path):
    packet = _ready_packet(tmp_path).to_dict()
    packet["unsafe_extra"] = {
        "raw_metrics_payload": {"views": 100},
        "raw_transcript_body": "SECRET_CANARY Authorization Bearer provider_headers",
    }

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")
    rendered = str(draft.to_dict())

    assert draft.redaction.approval_state_mutated is False
    assert draft.redaction.raw_metrics_included is False
    assert draft.redaction.raw_transcript_included is False
    assert draft.redaction.secrets_included is False
    assert draft.redaction.provider_headers_included is False
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_builder_does_not_invoke_approval_store_or_runtime_paths(tmp_path, monkeypatch):
    packet = _ready_packet(tmp_path)
    invoked = {
        "store": False,
        "executor": False,
        "replay": False,
        "evaluation": False,
        "promotion": False,
        "raw": False,
    }

    def forbidden(name):
        def inner(*args, **kwargs):
            invoked[name] = True
            raise AssertionError(f"{name} must not be invoked")

        return inner

    monkeypatch.setattr("src.core.runtime.policy.InMemoryApprovalStore.record", forbidden("store"), raising=False)
    monkeypatch.setattr("src.core.runtime.executor.PlaybookExecutor.execute", forbidden("executor"))
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", forbidden("replay"))
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", forbidden("evaluation"))
    monkeypatch.setattr("src.core.runtime.promotion_gate.PromotionGate.decide", forbidden("promotion"))
    monkeypatch.setattr(
        "src.core.content.performance_context.ContentPerformanceContextService.get_raw_metrics_snapshot",
        forbidden("raw"),
    )

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")

    assert draft.status == "draft"
    assert invoked == {
        "store": False,
        "executor": False,
        "replay": False,
        "evaluation": False,
        "promotion": False,
        "raw": False,
    }


def test_builder_source_has_no_ai_interactive_collection_or_network_path():
    source = Path("src/core/runtime/approval_request_draft.py").read_text(encoding="utf-8").lower()

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
