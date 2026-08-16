from __future__ import annotations

from dataclasses import replace

from src.core.runtime import EvaluationPolicy, SandboxEvaluationHarness, SandboxExecutionStore

from tests.test_phase66_sandbox_execution_store import _record


def _saved_payload(tmp_path):
    _, _, record = _record(tmp_path)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    return store.save(record)


def test_blocked_execution_allowed_only_by_policy(tmp_path):
    _, _, record = _record(tmp_path)
    blocked = replace(record, status="blocked", blocked_reasons=("capability_not_available",))
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    payload = store.save(blocked)

    rejected = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload)
    allowed = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(allow_blocked=True),
    )

    assert rejected.status == "failed"
    assert "blocked_not_allowed" in rejected.failures
    assert allowed.status == "warning"
    assert "capability_not_available" in allowed.warnings


def test_blocked_execution_rejected_when_policy_requires_completed(tmp_path):
    _, _, record = _record(tmp_path)
    blocked = replace(record, status="blocked", blocked_reasons=("unsupported_step_kind",))
    payload = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(blocked)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(allow_blocked=True, require_all_steps_completed=True),
    )

    assert result.status == "failed"
    assert "steps_not_completed" in result.failures


def test_required_step_kind_missing_fails(tmp_path):
    payload = _saved_payload(tmp_path)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(required_step_kinds=("list_publications",)),
    )

    assert result.status == "failed"
    assert "required_step_kind_missing" in result.failures


def test_forbidden_step_kind_present_fails(tmp_path):
    payload = _saved_payload(tmp_path)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(forbidden_step_kinds=("inspect_context",)),
    )

    assert result.status == "failed"
    assert "forbidden_step_kind_present" in result.failures


def test_warnings_allowed_or_disallowed(tmp_path):
    _, _, record = _record(tmp_path)
    blocked = replace(record, status="blocked", blocked_reasons=("raw_access_not_allowed",))
    payload = SandboxExecutionStore(tmp_path / "sandbox-executions.json").save(blocked)

    warning = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(allow_blocked=True, allow_warnings=True),
    )
    failed = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(allow_blocked=True, allow_warnings=False),
    )

    assert warning.status == "warning"
    assert "raw_access_not_allowed" in warning.warnings
    assert failed.status == "failed"


def test_mutation_and_raw_usage_fail_by_default(tmp_path):
    payload = _saved_payload(tmp_path)
    step = {**payload["step_results"][0], "mutation_used": True, "raw_access_used": True}
    payload = {**payload, "step_results": [step, *payload["step_results"][1:]]}

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload)

    assert result.status == "failed"
    assert "mutation_used" in result.failures
    assert "raw_access_used" in result.failures

