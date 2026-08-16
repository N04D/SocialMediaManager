from __future__ import annotations

from src.core.runtime import EvaluationPolicy, PromotionGate, PromotionPolicy, SandboxEvaluationHarness, SandboxExecutionStore

from tests.test_phase66_sandbox_execution_store import _record


def _clean_subject(tmp_path):
    _, _, record = _record(tmp_path)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    execution = store.save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(execution)
    return execution, evaluation


def test_passed_clean_evaluation_becomes_eligible(tmp_path):
    execution, evaluation = _clean_subject(tmp_path)

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(evaluation, execution_record=execution)

    assert decision.status == "eligible"
    assert decision.subject_execution_id == execution["execution_id"]
    assert decision.subject_evaluation_id == evaluation.evaluation_id
    assert PromotionGate().is_eligible(decision) is True
    assert decision.eligible_next_actions == ("allow_read_only_agent_consumption", "allow_sandbox_replay")
    assert decision.required_reviews == ()


def test_failed_evaluation_becomes_blocked(tmp_path):
    execution, _ = _clean_subject(tmp_path)
    failed = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        {**execution, "sandbox": False}
    )

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(failed, execution_record=execution)

    assert decision.status == "blocked"
    assert "evaluation_not_passed" in PromotionGate().explain(decision)
    assert "sandbox_not_true" in PromotionGate().explain(decision)


def test_warning_evaluation_becomes_needs_review_by_default(tmp_path):
    execution, _ = _clean_subject(tmp_path)
    warning = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        {**execution, "status": "blocked", "blocked_reasons": ["capability_not_available"]},
        policy=EvaluationPolicy(allow_blocked=True),
    )

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        warning,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(require_evaluation_passed=False),
    )

    assert decision.status == "needs_review"
    assert "manual_review" in decision.required_reviews


def test_warning_can_be_blocked_or_eligible_by_explicit_policy(tmp_path):
    execution, _ = _clean_subject(tmp_path)
    warning = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        {**execution, "status": "blocked", "blocked_reasons": ["raw_access_not_allowed"]},
        policy=EvaluationPolicy(allow_blocked=True),
    )

    blocked = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(warning, execution_record=execution)
    eligible = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        warning,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(
            require_evaluation_passed=False,
            allow_warnings=True,
            require_manual_review_for_warnings=False,
        ),
    )

    assert blocked.status == "blocked"
    assert eligible.status == "eligible"
