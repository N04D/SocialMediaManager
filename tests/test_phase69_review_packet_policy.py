from __future__ import annotations

from src.core.runtime import ManualReviewPacketBuilder, ReviewPacketPolicy

from tests.test_phase69_manual_review_packet import _eligible_subject


def test_missing_required_decision_blocks_packet(tmp_path):
    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(None)

    assert packet.status == "blocked_from_review"
    assert "missing_decision" in [reason.reason_code for reason in packet.review_reason]


def test_required_optional_object_missing_behavior(tmp_path):
    _, _, decision, _ = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        policy=ReviewPacketPolicy(require_evaluation=True, require_execution=True, require_plan=True),
    )

    reasons = [reason.reason_code for reason in packet.review_reason]
    assert packet.status == "blocked_from_review"
    assert "missing_evaluation" in reasons
    assert "missing_execution" in reasons
    assert "missing_plan" in reasons


def test_full_step_outputs_omitted_by_default(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    execution = {
        **execution,
        "step_results": [
            {
                **execution["step_results"][0],
                "output_ref_or_value": {"safe": "but still omitted"},
            },
            *execution["step_results"][1:],
        ],
    }

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )
    rendered = str(packet.to_dict())

    assert packet.redaction.full_step_outputs_included is False
    assert "but still omitted" not in rendered


def test_include_step_output_policy_only_sets_flag_not_raw_body(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
        policy=ReviewPacketPolicy(include_step_output=True),
    )

    assert packet.redaction.full_step_outputs_included is True
    assert "output_ref_or_value" not in str(packet.to_dict())


def test_unsafe_next_action_is_omitted(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    unsafe_decision = {
        **decision.to_dict(),
        "eligible_next_actions": [
            *decision.eligible_next_actions,
            "execute_production",
            "publish",
            "call_ai",
        ],
    }

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        unsafe_decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert "execute_production" not in packet.safe_next_actions
    assert "publish" not in packet.safe_next_actions
    assert "call_ai" not in packet.safe_next_actions
    assert "unsafe_next_action_omitted" in [reason.reason_code for reason in packet.review_reason]

