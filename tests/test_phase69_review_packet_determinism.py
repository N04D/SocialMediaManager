from __future__ import annotations

from src.core.runtime import ManualReviewPacketBuilder

from tests.test_phase69_manual_review_packet import _eligible_subject


def test_same_inputs_stable_packet_excluding_volatile_fields(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    first = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    ).to_dict()
    second = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T21:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    ).to_dict()

    for payload in (first, second):
        payload.pop("packet_id")
        payload.pop("generated_at")

    assert first == second


def test_reason_action_review_and_provenance_ordering_stable(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    unsafe_decision = {
        **decision.to_dict(),
        "eligible_next_actions": ["publish", "allow_sandbox_replay", "allow_manual_review"],
        "required_reviews": ["z-review", "a-review"],
    }

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        unsafe_decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    reason_keys = [(reason.severity, reason.subject_ref, reason.reason_code) for reason in packet.review_reason]
    assert reason_keys == sorted(reason_keys)
    assert packet.safe_next_actions == tuple(sorted(packet.safe_next_actions))
    assert packet.required_reviews == ("a-review", "z-review")
    assert sorted(packet.provenance.keys()) == [
        "builder_version",
        "decision_ref",
        "evaluation_ref",
        "execution_ref",
        "plan_ref",
        "policy",
    ]

