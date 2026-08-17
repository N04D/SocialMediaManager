from __future__ import annotations

from src.core.runtime import ExecutionReadinessReporter

from tests.test_phase77_execution_readiness_report import _governance_chain


def _stable_report(report):
    payload = report.to_dict()
    payload.pop("report_id", None)
    payload.pop("generated_at", None)
    return payload


def test_same_inputs_stable_excluding_report_id_and_generated_at(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)

    first = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )
    second = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:02:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    assert _stable_report(first) == _stable_report(second)


def test_check_ordering_is_stable(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)
    bad_preparation = {**preparation, "plan_id": "different", "requested_action_kind": "sandbox_replay"}

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=bad_preparation,
        claim=claim,
    )

    keys = [(check.severity, check.subject_ref, check.reason_code, check.check_id) for check in report.consistency_checks]
    assert keys == sorted(keys, key=lambda item: ({"error": "0", "warning": "1", "info": "2"}.get(item[0], "9"), item[1], item[2], item[3]))


def test_safe_next_actions_ordering_is_stable(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    assert report.safe_next_actions == tuple(sorted(report.safe_next_actions))
    assert report.safe_next_actions == (
        "expire_claim",
        "inspect_readiness",
        "open_non_production_attempt",
        "release_claim",
        "replay_sandbox",
    )


def test_subject_scope_fields_are_sorted(tmp_path):
    approval, promotion, eligibility, preparation, claim, _ = _governance_chain(tmp_path)

    report = ExecutionReadinessReporter(clock=lambda: "2026-08-17T15:01:00Z").build(
        approval_request=approval,
        promotion_decision=promotion,
        eligibility_decision=eligibility,
        preparation_record=preparation,
        claim=claim,
    )

    assert list(report.subject_scope) == sorted(report.subject_scope)
