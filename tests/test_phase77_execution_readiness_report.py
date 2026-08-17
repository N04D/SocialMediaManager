from __future__ import annotations

from dataclasses import replace

from src.core.runtime import (
    ExecutionAttemptLedger,
    ExecutionClaimStore,
    ExecutionPreparationBuilder,
    ExecutionPreparationStore,
    ExecutionReadinessReporter,
)

from tests.test_phase73_execution_preparation import _ready_inputs


def _governance_chain(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    preparation_record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )
    preparation_store = ExecutionPreparationStore(tmp_path / "preparations.json", clock=lambda: "2026-08-17T14:00:00Z")
    preparation = preparation_store.save(preparation_record)
    claim_store = ExecutionClaimStore(tmp_path / "claims.json", preparation_store=preparation_store)
    claim = claim_store.claim(preparation["preparation_id"], "worker:alpha", now="2026-08-17T15:00:00Z").claim
    attempt_ledger = ExecutionAttemptLedger(tmp_path / "attempts.json")
    return approval, promotion, eligibility, preparation, claim, attempt_ledger


def test_ready_governance_chain_reports_ready(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    assert report.status == "ready"
    assert report.subject_scope["approval_id"] == approval.approval_id
    assert report.subject_scope["promotion_decision_id"] == promotion.decision_id
    assert report.subject_scope["eligibility_decision_id"] == eligibility.decision_id
    assert report.subject_scope["preparation_id"] == preparation["preparation_id"]
    assert report.claim_summary["active"] is True
    assert "open_non_production_attempt" in report.safe_next_actions
    assert not report.blockers


def test_active_claim_and_noop_attempt_are_summarized(tmp_path):
    approval, promotion, eligibility, preparation, claim, ledger = _governance_chain(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt
    completed = ledger.complete_noop(attempt.attempt_id, now="2026-08-17T15:02:00Z").attempt

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:03:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=completed,
    )

    assert report.status == "ready"
    assert report.attempt_summary["mode"] == "no_op"
    assert report.attempt_summary["status"] == "completed_noop"
    assert report.attempt_summary["result"]["side_effects"] is False
    assert "replay_sandbox" in report.safe_next_actions
    assert "open_non_production_attempt" not in report.safe_next_actions


def test_report_summarize_returns_safe_core_fields(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    reporter = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z")
    report = reporter.build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    summary = reporter.summarize(report)

    assert summary["status"] == "ready"
    assert summary["blockers"] == []
    assert "inspect_readiness" in summary["safe_next_actions"]


def test_historical_noop_can_be_informational_when_readiness_not_required(tmp_path):
    approval, promotion, eligibility, preparation, claim, ledger = _governance_chain(tmp_path)
    attempt = ledger.open_attempt(claim, preparation, mode="simulation", now="2026-08-17T15:01:00Z").attempt
    completed = ledger.complete_noop(attempt.attempt_id, now="2026-08-17T15:02:00Z").attempt

    from src.core.runtime import ExecutionReadinessReportPolicy

    policy = ExecutionReadinessReportPolicy(
        require_approved=False,
        require_promotion_eligible=False,
        require_eligibility_eligible=False,
        require_preparation_ready=False,
        allow_warnings=True,
    )
    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:03:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=completed,
        policy=policy,
    )

    assert report.status == "informational"
