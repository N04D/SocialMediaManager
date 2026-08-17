from __future__ import annotations

from pathlib import Path

from src.core.runtime import ExecutionPreparationBuilder
from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase73_execution_preparation import _ready_inputs


def _reason_codes(record):
    return [reason.reason_code for reason in (*record.readiness_reasons, *record.blocked_reasons)]


def test_no_sensitive_canaries_or_raw_payloads_leak_into_record(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    unsafe_plan = {
        **plan.to_dict(),
        "metadata": {
            "secret": "SECRET_CANARY",
            "raw_metrics_payload": {"views": 1},
            "raw_transcript_body": "private transcript",
            "Authorization": "Bearer should-not-persist",
        },
    }

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        unsafe_plan,
    )
    rendered = str(record.to_dict())

    assert record.status == "blocked"
    assert "forbidden_data_present" in _reason_codes(record)
    assert "SECRET_CANARY" not in rendered
    assert "Authorization" not in rendered
    assert "Bearer" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_unsafe_redaction_and_runtime_markers_block(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    unsafe_eligibility = {
        **eligibility.to_dict(),
        "redaction": {"secrets_included": True, "provider_headers_included": True},
        "markers": {"ai_invoked": True, "network_invoked": True},
    }

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        unsafe_eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.status == "blocked"
    assert "unsafe_redaction" in _reason_codes(record)
    assert "forbidden_marker_present" in _reason_codes(record)
    assert record.redaction.secrets_included is False
    assert record.redaction.provider_headers_included is False
    assert record.redaction.execution_started is False
    assert record.redaction.production_mutation_used is False


def test_builder_does_not_invoke_execution_or_review_layers(monkeypatch, tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    calls: list[str] = []

    def marker(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("side-effect path invoked")

    monkeypatch.setattr("src.core.runtime.playbook_sandbox.ReadOnlyPlaybookSandbox.execute", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", marker)
    monkeypatch.setattr("src.core.runtime.promotion_gate.PromotionGate.decide", marker)
    monkeypatch.setattr("src.core.runtime.approval_state_machine.ApprovalStore.approve", marker)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.status == "ready"
    assert calls == []


def test_no_production_boundary_changes():
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


def test_source_has_no_execution_ai_network_or_provider_metric_reader_references():
    source = Path("src/core/runtime/execution_preparation.py").read_text(encoding="utf-8").lower()

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
