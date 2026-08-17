from __future__ import annotations

import json
from dataclasses import replace

from src.core.runtime import ControlledExecutor, ControlledExecutorInputBuilder

from tests.test_phase78_executor_input_builder import _ready_executor_input


def test_unsafe_action_blocks(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)
    unsafe = replace(input_record, requested_action_kind="publish")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(unsafe)

    assert result.status == "blocked"
    assert "unsafe_action_kind" in [reason.reason_code for reason in result.blocked_reasons]


def test_production_capability_blocks(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)
    with_mutation = replace(input_record, required_capabilities=("website.article.publish",))

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(with_mutation)

    assert result.status == "blocked"
    assert result.capabilities_checked == ()
    assert "production_capability_not_supported" in [reason.reason_code for reason in result.blocked_reasons]


def test_allowed_side_effects_block(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)
    bad = replace(input_record, allowed_side_effects=("external_write",))

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(bad)

    assert result.status == "blocked"
    assert result.side_effects_used == ()
    assert "side_effects_not_allowed" in [reason.reason_code for reason in result.blocked_reasons]


def test_input_and_result_do_not_leak_raw_or_secret_canaries(tmp_path):
    _, report, preparation, claim = _ready_executor_input(tmp_path)
    poisoned_report = replace(report, subject_scope={**report.subject_scope, "note": "SECRET_CANARY Bearer token"})

    input_record = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(poisoned_report, preparation, claim)
    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)
    rendered = json.dumps({"input": input_record.to_dict(), "result": result.to_dict()}, sort_keys=True)

    assert result.status == "validated"
    assert "SECRET_CANARY" not in rendered
    assert "Bearer" not in rendered
    assert "Authorization" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_result_redaction_flags_are_safe(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="no_op")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.redaction.raw_metrics_included is False
    assert result.redaction.raw_transcript_included is False
    assert result.redaction.secrets_included is False
    assert result.redaction.provider_headers_included is False
    assert result.redaction.execution_started is False
    assert result.redaction.simulation_only is True
    assert result.redaction.production_mutation_used is False
    assert result.redaction.external_write_used is False
    assert result.redaction.ai_call_used is False


def test_source_has_no_production_executor_or_remote_invocation_paths():
    import src.core.runtime.controlled_executor as module

    text = open(module.__file__, encoding="utf-8").read()
    forbidden = (
        "PlaybookExecutor",
        "ApprovalStore(",
        "ExecutionClaimStore(",
        "ExecutionAttemptLedger(",
        "OpenAI",
        "Anthropic",
        "requests.",
        "subprocess",
        "youtube.metrics.read",
    )
    assert all(marker not in text for marker in forbidden)
