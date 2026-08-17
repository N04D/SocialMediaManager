from __future__ import annotations

from src.core.runtime import (
    ApprovalRequestDraftBuilder,
    ApprovalRequestDraftPolicy,
    ApprovalStore,
    ExecutionEligibilityGate,
    PromotionGate,
    PromotionPolicy,
)

from tests.test_phase69_manual_review_packet import _eligible_subject, _needs_review_subject
from tests.test_phase70_approval_request_contract import _informational_packet


def _payload(value):
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def _eligible_bundle(tmp_path):
    execution, evaluation, promotion, plan = _eligible_subject(tmp_path)
    packet = _informational_packet(tmp_path)
    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        packet,
        "allow_read_only_agent_consumption",
        policy=ApprovalRequestDraftPolicy(allow_informational=True),
    )
    store = ApprovalStore(clock=lambda: "2026-08-17T11:00:00Z")
    approval = store.create_from_draft(draft)
    approved = store.approve(approval.approval_id, reviewer_id="reviewer-1").approval
    return promotion, approved, plan, execution


def test_matching_promotion_approval_plan_and_execution_are_eligible(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "eligible"
    assert decision.subject_execution_id == execution["execution_id"]
    assert decision.subject_promotion_decision_id == promotion.decision_id
    assert decision.subject_approval_id == approval.approval_id
    assert decision.requested_action_kind == "read_only_agent_consumption"
    assert decision.matched_scope["decision_matches"] is True
    assert decision.matched_scope["execution_matches"] is True
    assert decision.matched_scope["playbook_id_matches"] is True
    assert decision.matched_scope["playbook_version_matches"] is True


def test_scope_matches_execution_decision_and_plan_metadata(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert decision.matched_scope["decision_id"] == promotion.decision_id
    assert decision.matched_scope["execution_id"] == execution["execution_id"]
    plan_payload = _payload(plan)
    assert decision.matched_scope["playbook_id"] == plan_payload["playbook_id"]
    assert decision.matched_scope["playbook_version"] == plan_payload["playbook_version"]
    assert decision.provenance["promotion_ref"]["id"] == promotion.decision_id


def test_read_only_sandbox_metadata_preserved(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert execution["sandbox"] is True
    assert execution["read_only"] is True
    assert decision.redaction.execution_started is False
    assert decision.redaction.production_mutation_used is False


def test_promotion_needs_review_blocks_by_default(tmp_path):
    execution, evaluation, _, plan = _needs_review_subject(tmp_path)
    promotion = PromotionGate(clock=lambda: "2026-08-17T09:00:00Z").decide(
        evaluation,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(require_evaluation_passed=False),
    )
    _, approval, _, _ = _eligible_bundle(tmp_path / "approval")

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert decision.status == "blocked"
    assert "promotion_needs_review_blocked" in [reason.reason_code for reason in decision.reasons]


def test_missing_required_inputs_block(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    gate = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z")

    missing_promotion = gate.decide(None, approval, plan=plan, execution_record=execution)
    missing_approval = gate.decide(promotion, None, plan=plan, execution_record=execution)

    assert missing_promotion.status == "blocked"
    assert "promotion_missing" in [reason.reason_code for reason in missing_promotion.reasons]
    assert missing_approval.status == "blocked"
    assert "approval_missing" in [reason.reason_code for reason in missing_approval.reasons]
