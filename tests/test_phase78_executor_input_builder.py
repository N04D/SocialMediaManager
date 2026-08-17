from __future__ import annotations

from dataclasses import replace

from src.core.runtime import (
    ControlledExecutor,
    ControlledExecutorInputBuilder,
    ControlledExecutorPolicy,
    ExecutionReadinessReporter,
)

from tests.test_phase77_execution_readiness_report import _governance_chain


def _ready_executor_input(tmp_path, *, mode: str = "validate_only"):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )
    input_record = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(
        report,
        preparation,
        claim,
        mode=mode,
    )
    return input_record, report, preparation, claim


def test_ready_report_preparation_and_active_claim_build_input(tmp_path):
    input_record, report, preparation, claim = _ready_executor_input(tmp_path)

    assert input_record.readiness_report_id == report.report_id
    assert input_record.preparation_id == preparation["preparation_id"]
    assert input_record.claim_id == claim.claim_id
    assert input_record.playbook_id == preparation["playbook_id"]
    assert input_record.playbook_version == preparation["playbook_version"]
    assert input_record.requested_action_kind == "read_only_agent_consumption"
    assert input_record.allowed_side_effects == ()
    assert "production_mutation" in input_record.forbidden_side_effects
    assert "claim_mutation" in input_record.forbidden_side_effects
    assert input_record.redaction.production_mutation_used is False


def test_non_ready_report_blocks_when_executor_validates(tmp_path):
    input_record, report, preparation, claim = _ready_executor_input(tmp_path)
    blocked_report = replace(report, status="blocked")
    blocked_input = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(
        blocked_report,
        preparation,
        claim,
    )

    reasons = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").validate_input(blocked_input)

    assert "readiness_not_ready" in [reason.reason_code for reason in reasons]


def test_non_ready_preparation_and_inactive_claim_block(tmp_path):
    input_record, report, preparation, claim = _ready_executor_input(tmp_path)
    blocked_preparation = {**preparation, "status": "blocked", "store_status": "blocked"}
    released_claim = replace(claim, status="released")
    controlled_input = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(
        report,
        blocked_preparation,
        released_claim,
    )

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(controlled_input)

    assert result.status == "blocked"
    blockers = [reason.reason_code for reason in result.blocked_reasons]
    assert "preparation_not_ready" in blockers
    assert "claim_not_active" in blockers


def test_expired_claim_blocks(tmp_path):
    _, report, preparation, claim = _ready_executor_input(tmp_path)
    expired = replace(claim, lease_expires_at="2026-08-17T15:01:00Z")
    input_record = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(report, preparation, expired)

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.status == "blocked"
    assert "claim_expired" in [reason.reason_code for reason in result.blocked_reasons]


def test_policy_forbidden_side_effects_are_enforced(tmp_path):
    _, report, preparation, claim = _ready_executor_input(tmp_path)
    policy = ControlledExecutorPolicy(forbidden_side_effects=("production_mutation",))
    input_record = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(
        report,
        preparation,
        claim,
        policy=policy,
    )

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.status == "blocked"
    assert "forbidden_side_effects_missing" in [reason.reason_code for reason in result.blocked_reasons]
