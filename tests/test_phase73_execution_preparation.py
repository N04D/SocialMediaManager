from __future__ import annotations

from src.core.runtime import ExecutionEligibilityGate, ExecutionPreparationBuilder

from tests.test_phase72_execution_eligibility_gate import _eligible_bundle


def _ready_inputs(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    eligibility = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )
    return eligibility, approval, promotion, plan


def test_ready_inputs_create_ready_preparation(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.status == "ready"
    assert record.eligibility_decision_id == eligibility.decision_id
    assert record.approval_id == approval.approval_id
    assert record.promotion_decision_id == promotion.decision_id
    assert record.plan_id == plan.plan_id
    assert record.playbook_id == plan.playbook_id
    assert record.playbook_version == plan.playbook_version
    assert record.requested_action_kind == "read_only_agent_consumption"


def test_required_capabilities_forbidden_side_effects_and_fingerprint_present(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.required_capabilities == ("content.performance.context.read",)
    assert record.plan_fingerprint.startswith("plan_fingerprint_")
    assert set(record.forbidden_side_effects) == {
        "ai_call",
        "approval_state_mutation",
        "browser_automation",
        "external_write",
        "production_mutation",
        "raw_metrics_default",
        "raw_transcript_default",
        "scraping",
    }


def test_subject_scope_and_provenance_refs_preserved(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.subject_scope["approval_id"] == approval.approval_id
    assert record.subject_scope["eligibility_decision_id"] == eligibility.decision_id
    assert record.subject_scope["promotion_decision_id"] == promotion.decision_id
    assert record.subject_scope["plan_id"] == plan.plan_id
    assert record.provenance["eligibility_ref"]["id"] == eligibility.decision_id
    assert record.provenance["approval_ref"]["id"] == approval.approval_id
    assert record.provenance["promotion_ref"]["id"] == promotion.decision_id
    assert record.provenance["plan_ref"]["id"] == plan.plan_id


def test_summarize_returns_safe_core_fields(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")
    record = builder.prepare(eligibility, approval, promotion, plan)

    summary = builder.summarize(record)

    assert summary["status"] == "ready"
    assert summary["approval_id"] == approval.approval_id
    assert summary["eligibility_decision_id"] == eligibility.decision_id
    assert summary["plan_fingerprint"] == record.plan_fingerprint
