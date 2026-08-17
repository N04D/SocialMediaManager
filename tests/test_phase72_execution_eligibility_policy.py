from __future__ import annotations

from src.core.runtime import (
    ApprovalStore,
    ExecutionEligibilityGate,
    ExecutionEligibilityPolicy,
    PromotionGate,
    PromotionPolicy,
)

from tests.test_phase69_manual_review_packet import _needs_review_subject
from tests.test_phase72_execution_eligibility_gate import _eligible_bundle


def _payload(value):
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def test_approval_pending_rejected_expired_cancelled_and_blocked_block(tmp_path):
    promotion, approved, plan, execution = _eligible_bundle(tmp_path)
    gate = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z")
    statuses = {}

    for name in ("pending", "rejected", "cancelled", "expired", "blocked"):
        approval = approved.to_dict()
        approval["approval_id"] = f"approval-{name}"
        approval["status"] = name
        statuses[name] = gate.decide(promotion, approval, plan=plan, execution_record=execution)

    assert all(decision.status == "blocked" for decision in statuses.values())
    assert "approval_pending_blocks" in [reason.reason_code for reason in statuses["pending"].reasons]
    assert "approval_rejected_blocks" in [reason.reason_code for reason in statuses["rejected"].reasons]
    assert "approval_expired_blocks" in [reason.reason_code for reason in statuses["expired"].reasons]
    assert "approval_cancelled_blocks" in [reason.reason_code for reason in statuses["cancelled"].reasons]
    assert "approval_blocked_blocks" in [reason.reason_code for reason in statuses["blocked"].reasons]


def test_promotion_blocked_blocks(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    blocked = promotion.to_dict()
    blocked["status"] = "blocked"

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        blocked,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "blocked"
    assert "promotion_not_eligible" in [reason.reason_code for reason in decision.reasons]


def test_allow_needs_review_routes_to_needs_review(tmp_path):
    execution, evaluation, _, plan = _needs_review_subject(tmp_path)
    promotion = PromotionGate(clock=lambda: "2026-08-17T09:00:00Z").decide(
        evaluation,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(require_evaluation_passed=False),
    )
    _, approval, _, _ = _eligible_bundle(tmp_path / "approval")
    plan_payload = _payload(plan)
    approval_payload = approval.to_dict()
    approval_payload["scope"]["decision_id"] = promotion.decision_id
    approval_payload["scope"]["execution_id"] = execution["execution_id"]
    approval_payload["scope"]["playbook_id"] = plan_payload["playbook_id"]
    approval_payload["scope"]["playbook_version"] = plan_payload["playbook_version"]

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval_payload,
        plan=plan,
        execution_record=execution,
        policy=ExecutionEligibilityPolicy(allow_needs_review=True),
    )

    assert decision.status == "needs_review"
    assert "promotion_needs_review" in [reason.reason_code for reason in decision.reasons]


def test_allowed_action_kinds_enforced(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
        policy=ExecutionEligibilityPolicy(allowed_action_kinds=("manual_review",)),
    )

    assert decision.status == "blocked"
    assert "action_kind_not_allowed" in [reason.reason_code for reason in decision.reasons]


def test_scope_and_action_mismatch_block(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    mismatched = approval.to_dict()
    mismatched["scope"]["execution_id"] = "different-execution"
    mismatched["scope"]["requested_action_kind"] = "manual_review"

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        mismatched,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "blocked"
    reasons = [reason.reason_code for reason in decision.reasons]
    assert "scope_mismatch" in reasons
    assert "action_mismatch" in reasons


def test_raw_access_mutations_and_sandbox_requirements_block_by_default(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    unsafe_execution = {
        **execution,
        "sandbox": False,
        "read_only": False,
        "step_results": [
            {**execution["step_results"][0], "raw_access_used": True, "mutation_used": True},
        ],
    }

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=unsafe_execution,
    )

    reasons = [reason.reason_code for reason in decision.reasons]
    assert decision.status == "blocked"
    assert "execution_not_sandbox" in reasons
    assert "execution_not_read_only" in reasons
    assert "raw_access_used" in reasons
    assert "mutation_used" in reasons
