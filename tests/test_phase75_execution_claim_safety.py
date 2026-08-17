from __future__ import annotations

from pathlib import Path

from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime.capabilities import CapabilityMode

from tests.test_phase75_execution_claim_store import _saved_ready


def test_claim_release_and_expire_do_not_invoke_execution_or_review_layers(monkeypatch, tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    calls: list[str] = []

    def marker(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("side-effect path invoked")

    monkeypatch.setattr("src.core.runtime.playbook_sandbox.ReadOnlyPlaybookSandbox.execute", marker)
    monkeypatch.setattr("src.core.runtime.approval_state_machine.ApprovalStore.approve", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_execution" + "_store.SandboxReplayService.replay", marker)
    monkeypatch.setattr("src.core.runtime.sandbox_evaluation.SandboxEvaluationHarness.evaluate", marker)

    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    claim_store.release(claim.claim_id, claimant_id="worker:alpha", now="2026-08-17T15:01:00Z")
    second = claim_store.claim(preparation["preparation_id"], "worker:beta", now="2026-08-17T15:02:00Z").claim
    claim_store.expire(second.claim_id, now="2026-08-17T15:20:00Z")

    assert calls == []


def test_no_execution_lifecycle_statuses_are_emitted(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)
    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha").claim

    statuses = [item.status for item in claim_store.list()]

    assert claim.status == "claimed"
    assert "executing" not in statuses
    assert "executed" not in statuses
    assert "succeeded" not in statuses
    assert "failed_production" not in statuses
    assert "completed_production" not in statuses


def test_claim_records_have_safe_redaction_flags(tmp_path):
    preparation, _, claim_store = _saved_ready(tmp_path)

    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha").claim

    assert claim.redaction.raw_metrics_included is False
    assert claim.redaction.raw_transcript_included is False
    assert claim.redaction.secrets_included is False
    assert claim.redaction.provider_headers_included is False
    assert claim.redaction.approval_state_mutated is False
    assert claim.redaction.execution_started is False
    assert claim.redaction.production_mutation_used is False


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


def test_claim_store_source_has_no_execution_ai_network_or_provider_metric_reader_references():
    source = Path("src/core/runtime/execution_claim_store.py").read_text(encoding="utf-8").lower()

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
