from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionReadinessReportPolicy, ExecutionReadinessReporter

from tests.test_phase77_execution_readiness_report import _governance_chain


def _report(tmp_path, **overrides):
    approval, promotion, eligibility, preparation, claim, ledger = _governance_chain(tmp_path)
    values = {
        "approval_request": approval,
        "promotion_decision": promotion,
        "eligibility_decision": eligibility,
        "preparation_record": preparation,
        "claim": claim,
        "attempt": None,
    }
    values.update(overrides)
    return ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(**values), values


def test_pending_rejected_expired_approval_blocks(tmp_path):
    _, values = _report(tmp_path)

    for status in ("pending", "rejected", "expired", "cancelled", "blocked"):
        approval = replace(values["approval_request"], status=status)
        report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
            approval_request=approval,
            promotion_decision=values["promotion_decision"],
            eligibility_decision=values["eligibility_decision"],
            preparation_record=values["preparation_record"],
        )
        assert report.status == "blocked"
        assert f"approval_{status}_blocks" in [check.reason_code for check in report.blockers]


def test_promotion_eligibility_and_preparation_blocking_states_block(tmp_path):
    _, values = _report(tmp_path)

    promotion = replace(values["promotion_decision"], status="blocked")
    eligibility = replace(values["eligibility_decision"], status="blocked")
    stale_preparation = {**values["preparation_record"], "status": "stale", "store_status": "stale"}

    promotion_report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=values["approval_request"],
        promotion_decision=promotion,
        eligibility_decision=values["eligibility_decision"],
        preparation_record=values["preparation_record"],
    )
    eligibility_report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=values["approval_request"],
        promotion_decision=values["promotion_decision"],
        eligibility_decision=eligibility,
        preparation_record=values["preparation_record"],
    )
    preparation_report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=values["approval_request"],
        promotion_decision=values["promotion_decision"],
        eligibility_decision=values["eligibility_decision"],
        preparation_record=stale_preparation,
    )

    assert "promotion_blocked_blocks" in [check.reason_code for check in promotion_report.blockers]
    assert "eligibility_blocked_blocks" in [check.reason_code for check in eligibility_report.blockers]
    assert "preparation_stale_blocks" in [check.reason_code for check in preparation_report.blockers]


def test_mismatched_action_plan_playbook_and_idempotency_block(tmp_path):
    _, values = _report(tmp_path)
    preparation = {
        **values["preparation_record"],
        "idempotency_key": "different_key",
        "plan_id": "different_plan",
        "playbook_id": "different_playbook",
        "playbook_version": "99.0.0",
        "requested_action_kind": "sandbox_replay",
    }
    claim = replace(values["claim"], idempotency_key="claim_key")

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=values["approval_request"],
        promotion_decision=values["promotion_decision"],
        eligibility_decision=values["eligibility_decision"],
        preparation_record=preparation,
        claim=claim,
    )

    blockers = [check.reason_code for check in report.blockers]
    assert "requested_action_kind_mismatch" in blockers
    assert "plan_id_mismatch" in blockers
    assert "playbook_id_mismatch" in blockers
    assert "playbook_version_mismatch" in blockers
    assert "idempotency_key_mismatch" in blockers


def test_expired_claim_blocks_when_active_claim_required(tmp_path):
    _, values = _report(tmp_path)
    expired_claim = replace(values["claim"], lease_expires_at="2026-08-17T14:59:00Z")

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=values["approval_request"],
        promotion_decision=values["promotion_decision"],
        eligibility_decision=values["eligibility_decision"],
        preparation_record=values["preparation_record"],
        claim=expired_claim,
        policy=ExecutionReadinessReportPolicy(require_active_claim=True),
    )

    assert report.status == "blocked"
    assert "claim_expired" in [check.reason_code for check in report.blockers]


def test_active_attempt_warning_routes_per_policy(tmp_path):
    _, values = _report(tmp_path)
    attempt = values["attempt"]
    _, _, _, _, _, ledger = _governance_chain(tmp_path / "attempt")
    approval, promotion, eligibility, preparation, claim, ledger = _governance_chain(tmp_path / "attempt2")
    opened = ledger.open_attempt(claim, preparation, mode="no_op", now="2026-08-17T15:01:00Z").attempt

    default_report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:02:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=opened,
    )
    review_report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:02:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
        attempt=opened,
        policy=ExecutionReadinessReportPolicy(allow_needs_review=True),
    )

    assert default_report.status == "blocked"
    assert "active_attempt_present" in [check.reason_code for check in default_report.warnings]
    assert review_report.status == "needs_review"
