from __future__ import annotations

import json

from src.core.runtime import ExecutionReadinessReporter

from tests.test_phase77_execution_readiness_report import _governance_chain


def test_report_omits_raw_payloads_and_secret_canaries(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    poisoned_preparation = {**preparation, "metadata": {"note": "SECRET_CANARY Bearer token"}}

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=poisoned_preparation,
        claim=claim,
    )

    rendered = json.dumps(report.to_dict(), sort_keys=True)
    assert report.status == "blocked"
    assert "unsafe_payload" in [check.reason_code for check in report.blockers]
    assert "SECRET_CANARY" not in rendered
    assert "Bearer" not in rendered
    assert "Authorization" not in rendered
    assert "raw_metrics_payload" not in rendered
    assert "raw_transcript_body" not in rendered


def test_unsafe_redaction_blocks(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    unsafe_attempt = {
        "attempt_id": "attempt_1",
        "claim_id": claim.claim_id,
        "idempotency_key": preparation["idempotency_key"],
        "mode": "no_op",
        "preparation_id": preparation["preparation_id"],
        "requested_action_kind": preparation["requested_action_kind"],
        "status": "completed_noop",
        "redaction": {"raw_metrics_included": True},
    }

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=unsafe_attempt,
    )

    assert report.status == "blocked"
    assert "unsafe_redaction" in [check.reason_code for check in report.blockers]
    assert report.redaction.raw_metrics_included is False


def test_production_markers_and_status_are_blocked_without_leaking_unsafe_actions(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    attempt = {
        "attempt_id": "attempt_1",
        "claim_id": claim.claim_id,
        "idempotency_key": preparation["idempotency_key"],
        "mode": "no_op",
        "preparation_id": preparation["preparation_id"],
        "requested_action_kind": preparation["requested_action_kind"],
        "result": {"marker": "production_executor_invoked"},
        "status": "production_completed",
    }

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=attempt,
    )

    assert report.status == "blocked"
    blockers = [check.reason_code for check in report.blockers]
    assert "attempt_status_unsupported" in blockers
    assert "forbidden_marker_present" in blockers
    assert all(action not in report.safe_next_actions for action in ("execute_production", "publish", "mutate", "send", "call_ai"))


def test_reporter_source_has_no_execution_or_remote_invocation_paths():
    import src.core.runtime.execution_readiness_report as module

    text = open(module.__file__, encoding="utf-8").read()
    forbidden = (
        "PlaybookExecutor",
        "ExecutionAttemptLedger(",
        "ExecutionClaimStore(",
        "ApprovalStore(",
        "PromotionGate(",
        "SandboxReplayService",
        "OpenAI",
        "Anthropic",
        "requests.",
        "subprocess",
        "youtube.metrics.read",
    )
    assert all(marker not in text for marker in forbidden)


def test_report_redaction_flags_are_safe(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    assert report.redaction.raw_metrics_included is False
    assert report.redaction.raw_transcript_included is False
    assert report.redaction.secrets_included is False
    assert report.redaction.provider_headers_included is False
    assert report.redaction.approval_state_mutated is False
    assert report.redaction.execution_started is False
    assert report.redaction.production_mutation_used is False
    assert report.redaction.external_write_used is False
    assert report.redaction.ai_call_used is False
