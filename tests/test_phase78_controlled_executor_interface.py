from __future__ import annotations

from dataclasses import replace

from src.core.runtime import ControlledExecutor

from tests.test_phase78_executor_input_builder import _ready_executor_input


def test_validate_only_returns_validated(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="validate_only")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.status == "validated"
    assert result.mode == "validate_only"
    assert result.side_effects_used == ()
    assert result.output_summary["validated"] is True


def test_no_op_returns_simulated_noop_summary(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="no_op")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.status == "simulated"
    assert result.mode == "no_op"
    assert result.output_summary["completed"] is True
    assert result.output_summary["side_effects"] is False
    assert result.output_summary["production_mutation_used"] is False
    assert result.output_summary["external_write_used"] is False
    assert result.output_summary["ai_call_used"] is False
    assert result.output_summary["raw_access_used"] is False


def test_simulation_returns_deterministic_local_summary(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="simulation")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").execute(input_record)

    assert result.status == "simulated"
    assert result.output_summary["mode"] == "simulation"
    assert result.output_summary["simulated"] is True
    assert result.output_summary["side_effects"] is False
    assert result.output_summary["subject_scope"]["preparation_id"] == input_record.preparation_id


def test_production_and_unknown_modes_block(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path)
    production = replace(input_record, mode="production")
    unknown = replace(input_record, mode="warp_drive")
    executor = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z")

    production_result = executor.run(production)
    unknown_result = executor.run(unknown)

    assert production_result.status == "blocked"
    assert unknown_result.status == "blocked"
    assert "unsupported_mode" in [reason.reason_code for reason in production_result.blocked_reasons]
    assert "unsupported_mode" in [reason.reason_code for reason in unknown_result.blocked_reasons]


def test_read_only_capabilities_are_checked_structurally(tmp_path):
    input_record, _, _, _ = _ready_executor_input(tmp_path, mode="validate_only")

    result = ControlledExecutor(clock=lambda: "2026-08-17T15:03:00Z").run(input_record)

    assert result.status == "validated"
    assert result.capabilities_checked == ("content.performance.context.read",)
