from __future__ import annotations

from src.core.runtime import ExecutionPreparationBuilder, ExecutionPreparationPolicy

from tests.test_phase73_execution_preparation import _ready_inputs


def _reason_codes(record):
    return [reason.reason_code for reason in (*record.readiness_reasons, *record.blocked_reasons)]


def test_blocked_when_eligibility_is_blocked(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    blocked_eligibility = {**eligibility.to_dict(), "status": "blocked"}

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        blocked_eligibility,
        approval,
        promotion,
        plan,
    )

    assert record.status == "blocked"
    assert "eligibility_not_eligible" in _reason_codes(record)


def test_blocked_when_approval_is_not_approved(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")

    for status in ("pending", "rejected", "expired", "cancelled"):
        record = builder.prepare(
            eligibility,
            {**approval.to_dict(), "status": status},
            promotion,
            plan,
        )

        assert record.status == "blocked"
        assert "approval_not_approved" in _reason_codes(record)


def test_blocked_when_promotion_is_not_eligible(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")

    blocked = builder.prepare(eligibility, approval, {**promotion.to_dict(), "status": "blocked"}, plan)
    review = builder.prepare(eligibility, approval, {**promotion.to_dict(), "status": "needs_review"}, plan)

    assert blocked.status == "blocked"
    assert review.status == "blocked"
    assert "promotion_not_eligible" in _reason_codes(blocked)
    assert "promotion_not_eligible" in _reason_codes(review)


def test_allow_needs_review_routes_to_needs_review(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        {**eligibility.to_dict(), "status": "needs_review"},
        approval,
        {**promotion.to_dict(), "status": "needs_review"},
        plan,
        policy=ExecutionPreparationPolicy(allow_needs_review=True),
    )

    assert record.status == "needs_review"
    assert "eligibility_needs_review" in _reason_codes(record)
    assert "promotion_needs_review" in _reason_codes(record)


def test_non_executable_plan_blocks_and_copies_plan_blocker(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    plan_payload = {**plan.to_dict(), "executable": False, "blocked_reasons": ["capability_not_available"]}

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan_payload,
    )

    assert record.status == "blocked"
    assert "plan_not_executable" in _reason_codes(record)
    assert "plan_blocked" in _reason_codes(record)


def test_raw_and_mutation_requirements_block_by_default_and_can_be_allowed(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    plan_payload = {**plan.to_dict(), "raw_access_required": True, "mutation_required": True}
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")

    blocked = builder.prepare(eligibility, approval, promotion, plan_payload)
    allowed = builder.prepare(
        eligibility,
        approval,
        promotion,
        plan_payload,
        policy=ExecutionPreparationPolicy(allow_raw_access=True, allow_mutations=True),
    )

    assert blocked.status == "blocked"
    assert "raw_access_required" in _reason_codes(blocked)
    assert "mutation_required" in _reason_codes(blocked)
    assert allowed.status == "ready"


def test_allowed_action_kinds_are_enforced(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval,
        promotion,
        plan,
        policy=ExecutionPreparationPolicy(allowed_action_kinds=("manual_review",)),
    )

    assert record.status == "blocked"
    assert "action_kind_not_allowed" in _reason_codes(record)


def test_missing_plan_fingerprint_blocks_when_required(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    builder = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z")
    builder.fingerprint_plan = lambda _plan: ""

    record = builder.prepare(eligibility, approval, promotion, plan)

    assert record.status == "blocked"
    assert "plan_fingerprint_missing" in _reason_codes(record)


def test_action_and_playbook_version_mismatch_block(tmp_path):
    eligibility, approval, promotion, plan = _ready_inputs(tmp_path)
    approval_payload = approval.to_dict()
    approval_payload["requested_action_kind"] = "manual_review"
    approval_payload["scope"] = {**approval_payload["scope"], "playbook_version": "v-mismatch"}

    record = ExecutionPreparationBuilder(clock=lambda: "2026-08-17T13:00:00Z").prepare(
        eligibility,
        approval_payload,
        promotion,
        plan,
    )

    assert record.status == "blocked"
    assert "action_mismatch" in _reason_codes(record)
    assert "playbook_version_mismatch" in _reason_codes(record)
