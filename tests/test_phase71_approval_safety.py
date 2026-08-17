from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import ApprovalRequestDraftBuilder, ApprovalStore
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase70_approval_request_contract import _ready_packet


def _approval(tmp_path):
    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:00:00Z").build(
        _ready_packet(tmp_path),
        "allow_manual_review",
    )
    store = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z")
    return store, store.create_from_draft(draft)


def test_approval_request_and_audit_exclude_secrets_and_raw_payloads(tmp_path):
    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:00:00Z").build(
        _ready_packet(tmp_path),
        "allow_manual_review",
    ).to_dict()
    draft["unsafe_extra"] = {
        "raw_metrics_payload": {"views": 100},
        "raw_transcript_body": "SECRET_CANARY Authorization Bearer provider_headers",
    }

    approval = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft)
    rendered = str(approval.to_dict())

    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered
    assert approval.redaction.approval_state_mutated is True
    assert approval.redaction.execution_started is False
    assert approval.redaction.production_mutation_used is False


def test_approved_does_not_invoke_runtime_paths(tmp_path, monkeypatch):
    store, approval = _approval(tmp_path)
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

    result = store.approve(approval.approval_id, reviewer_id="reviewer-1")

    assert result.status == "approved"
    assert invoked == {"executor": False, "replay": False, "evaluation": False, "promotion": False, "raw": False}


def test_audit_events_exclude_secrets(tmp_path):
    store, approval = _approval(tmp_path)
    store.reject(approval.approval_id, reviewer_id="SECRET_CANARY Authorization Bearer", reason="raw_metrics_payload")

    rendered = str([event.to_dict() for event in store.audit_events(approval.approval_id)])

    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered


def test_store_source_has_no_ai_interactive_collection_or_network_path():
    source = Path("src/core/runtime/approval_state_machine.py").read_text(encoding="utf-8").lower()

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
