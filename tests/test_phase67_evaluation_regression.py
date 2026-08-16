from __future__ import annotations

from src.core.runtime import (
    EvaluationPolicy,
    ReadOnlyPlaybookSandbox,
    SandboxEvaluationHarness,
    SandboxExecutionStore,
    SandboxReplayResult,
    SandboxReplayService,
)

from tests.test_phase66_sandbox_replay import _saved_execution


def test_matched_comparison_passes(tmp_path):
    context, plan, record, store = _saved_execution(tmp_path)
    replay = SandboxReplayService(
        store=store,
        sandbox=ReadOnlyPlaybookSandbox(clock=lambda: "2026-08-16T16:00:00Z"),
    ).compare_replay(record.execution_id, context, plan=plan)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(replay)

    assert replay.matched is True
    assert result.status == "passed"
    assert result.failures == ()


def test_mismatched_comparison_warns_or_fails_depending_policy(tmp_path):
    comparison = {
        "original_execution_id": "sandbox_execution_original",
        "matched": False,
        "original_fingerprint": "a" * 64,
        "replay_fingerprint": "b" * 64,
        "differences": ("output_changed",),
    }

    warning = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(comparison)
    failed = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(
        comparison,
        policy=EvaluationPolicy(allow_warnings=False),
    )

    assert warning.status == "warning"
    assert "replay_differed" in warning.warnings
    assert failed.status == "failed"


def test_allowed_difference_code_is_warning(tmp_path):
    comparison = {
        "original_execution_id": "sandbox_execution_original",
        "matched": False,
        "original_fingerprint": "a" * 64,
        "replay_fingerprint": "b" * 64,
        "differences": ("output_changed",),
    }

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(
        comparison,
        policy=EvaluationPolicy(allowed_difference_codes=("output_changed",)),
    )

    assert result.status == "warning"
    assert "allowed_difference_code" in result.warnings


def test_forbidden_difference_code_fails(tmp_path):
    comparison = SandboxReplayResult(
        original_execution_id="sandbox_execution_original",
        replay_execution_id="sandbox_execution_replay",
        matched=False,
        original_fingerprint="a" * 64,
        replay_fingerprint="b" * 64,
        differences=("redaction_changed",),
        status="completed",
        provenance={},
    )

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(comparison)

    assert result.status == "failed"
    assert "forbidden_difference_code" in result.failures


def test_evaluate_comparison_does_not_auto_replay(tmp_path, monkeypatch):
    invoked = {"replay": False}

    def forbidden_replay(*args, **kwargs):
        invoked["replay"] = True
        raise AssertionError("evaluation must not start replay")

    monkeypatch.setattr("src.core.runtime.sandbox_execution_store.SandboxReplayService.replay", forbidden_replay)

    result = SandboxEvaluationHarness(clock=lambda: "2026-08-16T17:00:00Z").evaluate_comparison(
        {
            "original_execution_id": "sandbox_execution_original",
            "matched": True,
            "original_fingerprint": "a" * 64,
            "replay_fingerprint": "a" * 64,
            "differences": (),
        }
    )

    assert result.status == "passed"
    assert invoked == {"replay": False}

