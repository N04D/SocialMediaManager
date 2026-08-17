from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ExecutionPreparationBuilder

from tests.test_phase73_execution_preparation import _ready_inputs


def _stable_record_payload(record):
    payload = record.to_dict()
    payload.pop("preparation_id", None)
    payload.pop("created_at", None)
    return payload


def test_same_inputs_are_stable_except_id_and_timestamp(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")

    first = builder.prepare(eligibility, approval, promotion, plan)
    second = builder.prepare(eligibility, approval, promotion, plan)

    assert _stable_record_payload(first) == _stable_record_payload(second)


def test_plan_fingerprint_ignores_generated_at_and_is_stable(tmp_path):
    _, _, _, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")
    payload = plan.to_dict()

    first = builder.fingerprint_plan({**payload, "generated_at": "2026-08-17T01:00:00Z"})
    second = builder.fingerprint_plan({**payload, "generated_at": "2026-08-17T02:00:00Z"})

    assert first == second
    assert first.startswith("plan_fingerprint_")


def test_plan_fingerprint_changes_when_stable_plan_content_changes(tmp_path):
    _, _, _, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")
    payload = plan.to_dict()

    first = builder.fingerprint_plan(payload)
    second = builder.fingerprint_plan({**payload, "required_capabilities": ["content.performance.context.read", "extra.read"]})

    assert first != second


def test_ordering_is_deterministic_for_collections(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    plan_payload = {
        **plan.to_dict(),
        "blocked_reasons": ["z_blocker", "a_blocker"],
        "required_capabilities": ["z.read", "a.read"],
        "executable": False,
    }

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan_payload,
    )

    assert record.required_capabilities == ("a.read", "z.read")
    assert record.forbidden_side_effects == tuple(sorted(record.forbidden_side_effects))
    assert list(record.subject_scope) == sorted(record.subject_scope)
    assert list(record.provenance) == sorted(record.provenance)
    assert [reason.reason_code for reason in record.blocked_reasons] == sorted(
        reason.reason_code for reason in record.blocked_reasons
    )


def test_semantic_equivalence_is_stable_with_different_output_id_timestamp(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    first = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
    )
    second = replace(
        first,
        preparation_id="execution_preparation_different",
        created_at="2026-08-17T14:00:00Z",
    )

    assert _stable_record_payload(first) == _stable_record_payload(second)
