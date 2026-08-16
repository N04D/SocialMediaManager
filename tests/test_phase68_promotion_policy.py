from __future__ import annotations

from src.core.runtime import (
    EvaluationPolicy,
    PromotionGate,
    PromotionPolicy,
    SandboxEvaluationHarness,
    SandboxExecutionStore,
)

from tests.test_phase66_sandbox_execution_store import _record


def _subject(tmp_path):
    _, _, record = _record(tmp_path)
    execution = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(record)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(execution)
    return execution, evaluation


def test_require_replay_match_blocks_when_absent(tmp_path):
    execution, evaluation = _subject(tmp_path)

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record=execution,
        policy=PromotionPolicy(require_replay_match=True),
    )

    assert decision.status == "blocked"
    assert "replay_match_required" in PromotionGate().explain(decision)


def test_require_replay_match_allows_embedded_match(tmp_path):
    execution, evaluation = _subject(tmp_path)

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={**execution, "replay_result": {"matched": True}},
        policy=PromotionPolicy(require_replay_match=True),
    )

    assert decision.status == "eligible"


def test_forbidden_reason_code_blocks(tmp_path):
    execution, _ = _subject(tmp_path)
    evaluation = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(
        {**execution, "status": "blocked", "blocked_reasons": ["capability_not_available"]},
        policy=EvaluationPolicy(allow_blocked=True),
    )

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={**execution, "status": "completed"},
        policy=PromotionPolicy(
            require_evaluation_passed=False,
            allow_warnings=True,
            require_manual_review_for_warnings=False,
            forbidden_reason_codes=("capability_not_available",),
        ),
    )

    assert decision.status == "blocked"
    assert "forbidden_reason_code" in PromotionGate().explain(decision)


def test_deprecated_playbook_warning_routes_to_review(tmp_path):
    execution, evaluation = _subject(tmp_path)
    plan = {
        "schema_version": "playbook-plan.v1",
        "selection_result": {
            "selected": [{"playbook_id": "content.performance.observe", "version": "0.9.0", "status": "deprecated"}]
        },
    }

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record=execution,
        plan=plan,
    )

    assert decision.status == "needs_review"
    assert "deprecated_playbook_review" in decision.required_reviews
    assert "deprecated_playbook_used" in PromotionGate().explain(decision)


def test_blocked_execution_not_eligible(tmp_path):
    execution, evaluation = _subject(tmp_path)

    decision = PromotionGate(clock=lambda: "2026-08-16T19:00:00Z").decide(
        evaluation,
        execution_record={**execution, "status": "blocked"},
    )

    assert decision.status == "blocked"
    assert "blocked_execution_not_allowed" in PromotionGate().explain(decision)

