from __future__ import annotations

from src.core.runtime import (
    EvaluationPolicy,
    ManualReviewPacketBuilder,
    PromotionGate,
    PromotionPolicy,
    SandboxEvaluationHarness,
    SandboxExecutionStore,
)

from tests.test_phase65_read_only_sandbox import _plan
from tests.test_phase66_sandbox_execution_store import _record


def _eligible_subject(tmp_path):
    context, plan, record = _record(tmp_path)
    execution = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(execution)
    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(evaluation, execution_record=execution)
    return execution, evaluation, decision, plan


def _needs_review_subject(tmp_path):
    context, plan = _plan(
        tmp_path,
        [{"step_id": "raw", "name": "Raw", "kind": "inspect_context", "raw_access_required": True}],
    )
    from src.core.runtime import ReadOnlyPlaybookSandbox

    record = ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T17:00:00Z").execute(plan, context)
    execution = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        execution,
        policy=EvaluationPolicy(allow_blocked=True),
    )
    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(require_evaluation_passed=False),
    )
    return execution, evaluation, decision, plan


def test_needs_review_decision_creates_ready_for_review_packet(tmp_path):
    execution, evaluation, decision, plan = _needs_review_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert packet.status == "ready_for_review"
    assert packet.subject_decision_id == decision.decision_id
    assert "manual_review" in packet.required_reviews
    assert "decision_needs_review" in [reason.reason_code for reason in packet.review_reason]


def test_eligible_decision_creates_informational_packet(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert packet.status == "informational"
    assert packet.decision_summary.status == "eligible"
    assert "decision_eligible" in [reason.reason_code for reason in packet.review_reason]


def test_blocked_decision_creates_informational_or_blocked_packet(tmp_path):
    execution, _, _, plan = _eligible_subject(tmp_path)
    failed = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate({**execution, "sandbox": False})
    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(failed, execution_record=execution)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=failed,
        execution_record=execution,
        plan=plan,
    )

    assert packet.status == "blocked_from_review"
    assert "decision_blocked" in [reason.reason_code for reason in packet.review_reason]
    assert "evaluation_failed" in [reason.reason_code for reason in packet.review_reason]


def test_missing_optional_objects_add_reason_codes(tmp_path):
    _, _, decision, _ = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(decision)

    reasons = [reason.reason_code for reason in packet.review_reason]
    assert packet.status == "informational"
    assert "missing_evaluation" in reasons
    assert "missing_execution" in reasons
    assert "missing_plan" in reasons


def test_decision_evaluation_execution_and_plan_summaries(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)

    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-16T20:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert packet.decision_summary.reason_codes == ()
    assert packet.decision_summary.safe_next_actions == ("allow_read_only_agent_consumption", "allow_sandbox_replay")
    assert packet.evaluation_summary.check_counts["passed"] > 0
    assert packet.evaluation_summary.subject_fingerprint == execution["fingerprint"]
    assert packet.execution_summary.step_counts_by_status == {"completed": 2}
    assert packet.execution_summary.fingerprint == execution["fingerprint"]
    assert packet.plan_summary.executable is True
    assert packet.plan_summary.step_count == 2
    assert "content.performance.context.read" in packet.plan_summary.required_capabilities

