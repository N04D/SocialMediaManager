from __future__ import annotations

from src.core.runtime import ExecutionEligibilityGate

from tests.test_phase72_execution_eligibility_gate import _eligible_bundle


def _stable(payload):
    cleaned = dict(payload)
    cleaned.pop("decision_id", None)
    cleaned.pop("decided_at", None)
    return cleaned


def test_same_inputs_stable_excluding_volatile_fields(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    first = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )
    second = ExecutionEligibilityGate(clock=lambda: "2026-08-17T13:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert _stable(first.to_dict()) == _stable(second.to_dict())
    assert first.decision_id != second.decision_id
    assert first.decided_at != second.decided_at


def test_reason_and_scope_ordering_is_stable(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)
    mismatched = approval.to_dict()
    mismatched["scope"] = {
        "z": "z",
        "requested_action_kind": "manual_review",
        "playbook_version": "wrong",
        "playbook_id": "wrong",
        "execution_id": "wrong",
        "decision_id": "wrong",
    }

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        mismatched,
        plan=plan,
        execution_record=execution,
    )
    payload = decision.to_dict()

    assert list(payload["matched_scope"].keys()) == sorted(payload["matched_scope"].keys())
    assert [reason["reason_code"] for reason in payload["reasons"]] == sorted(
        [reason["reason_code"] for reason in payload["reasons"]]
    )
    assert list(payload["blocked_capabilities"]) == sorted(payload["blocked_capabilities"])


def test_provenance_refs_are_deterministic(tmp_path):
    promotion, approval, plan, execution = _eligible_bundle(tmp_path)

    decision = ExecutionEligibilityGate(clock=lambda: "2026-08-17T12:00:00Z").decide(
        promotion,
        approval,
        plan=plan,
        execution_record=execution,
    )

    assert list(decision.provenance.keys()) == sorted(decision.provenance.keys())
    assert decision.provenance["approval_ref"]["id"] == approval.approval_id
    assert decision.provenance["execution_ref"]["id"] == execution["execution_id"]
    assert decision.provenance["promotion_ref"]["id"] == promotion.decision_id
