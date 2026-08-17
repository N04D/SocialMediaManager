from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ApprovalRequestDraftPolicy, ManualReviewPacketBuilder

from tests.test_phase69_manual_review_packet import _eligible_subject, _needs_review_subject


def _ready_packet(tmp_path):
    execution, evaluation, decision, plan = _needs_review_subject(tmp_path)
    return ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )


def _informational_packet(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    return ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )


def test_informational_packet_allowed_only_by_explicit_policy(tmp_path):
    packet = _informational_packet(tmp_path)
    builder = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z")

    default = builder.build(packet, "allow_read_only_agent_consumption")
    allowed = builder.build(
        packet,
        "allow_read_only_agent_consumption",
        policy=ApprovalRequestDraftPolicy(allow_informational=True),
    )

    assert default.status == "not_requestable"
    assert allowed.status == "draft"
    assert allowed.requested_action_kind == "read_only_agent_consumption"


def test_allowed_action_kinds_are_enforced(tmp_path):
    packet = _ready_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(
        packet,
        "allow_sandbox_replay",
        policy=ApprovalRequestDraftPolicy(allowed_action_kinds=("manual_review",)),
    )

    assert draft.status == "not_requestable"
    assert draft.requested_action_kind == "sandbox_replay"
    assert "action_kind_not_allowed" in [reason.reason_code for reason in draft.reason_codes]


def test_reviewer_role_defaults_from_policy(tmp_path):
    packet = _ready_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(
        packet,
        "allow_manual_review",
        policy=ApprovalRequestDraftPolicy(default_reviewer_role="operator"),
    )

    assert draft.status == "draft"
    assert draft.reviewer_role == "operator"


def test_expiration_set_only_when_configured(tmp_path):
    packet = _ready_packet(tmp_path)
    builder = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z")

    no_expiration = builder.build(packet, "allow_manual_review")
    expiring = builder.build(
        packet,
        "allow_manual_review",
        policy=ApprovalRequestDraftPolicy(default_expiration_hours=24),
    )

    assert no_expiration.expires_at is None
    assert expiring.expires_at == "2026-08-18T11:00:00Z"


def test_no_production_action_kind_allowed(tmp_path):
    packet = _ready_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "publish")

    assert draft.status == "not_requestable"
    assert draft.requested_action_kind == "unsupported"
    assert "publish" not in str(draft.to_dict())
    assert "unsafe_action_omitted" in [reason.reason_code for reason in draft.reason_codes]


def test_available_actions_are_policy_limited(tmp_path):
    packet = _ready_packet(tmp_path)

    actions = ApprovalRequestDraftBuilder().available_actions(
        packet,
        policy=ApprovalRequestDraftPolicy(allowed_action_kinds=("manual_review",)),
    )

    assert actions == ("manual_review",)
