from __future__ import annotations

from src.core.runtime import EvaluationPolicy, PromotionGate, PromotionPolicy, SandboxEvaluationHarness, SandboxExecutionStore

from tests.test_phase66_sandbox_execution_store import _record


def _subject(tmp_path):
    _, _, record = _record(tmp_path)
    execution = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(execution)
    return execution, evaluation


def test_same_inputs_stable_decision_excluding_volatile_fields(tmp_path):
    execution, evaluation = _subject(tmp_path)
    first = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(evaluation, execution_record=execution).to_dict()
    second = PromotionGate(clock=lambda: "2026-08-16T20:00:00Z").decide(evaluation, execution_record=execution).to_dict()

    for payload in (first, second):
        payload.pop("decision_id")
        payload.pop("decided_at")

    assert first == second


def test_reason_ordering_is_stable(tmp_path):
    execution, _ = _subject(tmp_path)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        {**execution, "status": "blocked", "blocked_reasons": ["raw_access_not_allowed", "capability_not_available"]},
        policy=EvaluationPolicy(allow_blocked=True),
    )

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={
            **execution,
            "status": "blocked",
            "redaction": {**execution["redaction"], "raw_metrics_included": True},
        },
        policy=PromotionPolicy(require_evaluation_passed=False, allow_warnings=True),
    )

    keys = [(reason.severity, reason.subject_ref, reason.reason_code) for reason in decision.reasons]
    assert keys == sorted(keys)
    assert decision.required_reviews == tuple(sorted(decision.required_reviews))
    assert decision.eligible_next_actions == tuple(sorted(decision.eligible_next_actions))
    assert decision.blocked_capabilities == tuple(sorted(decision.blocked_capabilities))

