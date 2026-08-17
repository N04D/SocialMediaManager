from __future__ import annotations

from src.core.runtime import ControlledExecutor, ControlledExecutorInputBuilder

from tests.test_phase78_executor_input_builder import _ready_executor_input


def _stable_input(input_record):
    payload = input_record.to_dict()
    payload.pop("input_id", None)
    payload.pop("created_at", None)
    return payload


def _stable_result(result):
    payload = result.to_dict()
    payload.pop("result_id", None)
    payload.pop("created_at", None)
    return payload


def test_same_readiness_preparation_claim_produce_stable_input_except_volatile_fields(tmp_path):
    _, report, preparation, claim = _ready_executor_input(tmp_path)

    first = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:02:00Z").build(report, preparation, claim, mode="simulation")
    second = ControlledExecutorInputBuilder(clock=lambda: "2026-08-17T15:03:00Z").build(report, preparation, claim, mode="simulation")

    assert _stable_input(first) == _stable_input(second)


def test_same_input_produces_stable_result_except_volatile_fields(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="simulation")

    first = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)
    second = ControlledExecutor(clock=lambda: "2026-08-17T15:04:00Z").run(input_record)

    assert _stable_result(first) == _stable_result(second)


def test_ordering_is_stable_for_side_effects_capabilities_scope_and_blockers(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)

    assert input_record.forbidden_side_effects == tuple(sorted(input_record.forbidden_side_effects))
    assert input_record.required_capabilities == tuple(sorted(input_record.required_capabilities))
    assert list(input_record.subject_scope) == sorted(input_record.subject_scope)

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.capabilities_checked == tuple(sorted(result.capabilities_checked))
    assert result.blocked_reasons == tuple(sorted(result.blocked_reasons, key=lambda reason: (reason.severity, reason.subject_ref, reason.reason_code)))


def test_blocked_reasons_order_is_stable(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)
    bad = input_record.__class__(
        **{
            **input_record.to_dict(),
            "allowed_side_effects": ("external_write",),
            "mode": "production",
            "requested_action_kind": "publish",
            "required_capabilities": ("website.article.publish",),
        }
    )

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(bad)

    assert [reason.reason_code for reason in result.blocked_reasons] == [
        "production_capability_not_supported",
        "side_effects_not_allowed",
        "unsupported_mode",
        "unsafe_action_kind",
    ]
