from __future__ import annotations

from dataclasses import replace

from src.core.runtime import EvaluationPolicy, SandboxEvaluationHarness, SandboxExecutionStore

from tests.test_phase66_sandbox_execution_store import _record


def _saved_payload(tmp_path):
    _, _, record = _record(tmp_path)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    return store.save(record)


def test_clean_sandbox_record_passes(tmp_path):
    payload = _saved_payload(tmp_path)
    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload)

    assert result.status == "passed"
    assert result.execution_id == payload["execution_id"]
    assert result.subject_fingerprint == payload["fingerprint"]
    assert result.failures == ()
    assert {check.status for check in result.checks} == {"passed"}


def test_evaluate_from_store_loads_record_by_execution_id(tmp_path):
    _, _, record = _record(tmp_path)
    store = SandboxExecutionStore(tmp_path / "sandbox-executions.json")
    store.save(record)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_from_store(
        record.execution_id,
        store,
    )

    assert result.status == "passed"
    assert result.execution_id == record.execution_id


def test_missing_fingerprint_fails(tmp_path):
    payload = _saved_payload(tmp_path)
    payload.pop("fingerprint")

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload)

    assert result.status == "failed"
    assert "fingerprint_missing_or_invalid" in result.failures


def test_sandbox_or_read_only_violation_fails(tmp_path):
    payload = _saved_payload(tmp_path)

    sandbox_false = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        {**payload, "sandbox": False}
    )
    read_only_false = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        {**payload, "read_only": False}
    )

    assert "sandbox_not_true" in sandbox_false.failures
    assert "read_only_not_true" in read_only_false.failures


def test_deterministic_result_excluding_volatile_fields(tmp_path):
    payload = _saved_payload(tmp_path)
    first = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(payload).to_dict()
    second = SandboxEvaluationHarness(clock=lambda: "2026-08-16T18:00:00Z").evaluate(payload).to_dict()

    for item in (first, second):
        item.pop("evaluation_id")
        item.pop("evaluated_at")

    assert first == second


def test_check_ordering_is_stable(tmp_path):
    payload = _saved_payload(tmp_path)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate(
        payload,
        policy=EvaluationPolicy(required_step_kinds=("check_metrics_available", "inspect_context")),
    )

    check_keys = [(check.subject_ref, check.check_id, check.reason_code) for check in result.checks]
    assert check_keys == sorted(check_keys)

