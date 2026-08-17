from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ManualReviewPacketBuilder, ReviewPacketPolicy

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


def test_ready_for_review_packet_creates_manual_review_draft(tmp_path):
    packet = _ready_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")

    assert draft.status == "draft"
    assert draft.packet_id == packet.packet_id
    assert draft.subject_execution_id == packet.subject_execution_id
    assert draft.subject_decision_id == packet.subject_decision_id
    assert draft.requested_action == "allow_manual_review"
    assert draft.requested_action_kind == "manual_review"
    assert draft.reviewer_role == "human_reviewer"
    assert draft.scope["packet_id"] == packet.packet_id
    assert draft.scope["execution_id"] == packet.subject_execution_id
    assert draft.scope["decision_id"] == packet.subject_decision_id
    assert draft.scope["playbook_id"] == packet.plan_summary.playbook_id


def test_informational_packet_not_requestable_by_default(tmp_path):
    packet = _informational_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(
        packet,
        "allow_read_only_agent_consumption",
    )

    assert draft.status == "not_requestable"
    assert "packet_not_ready_for_review" in [reason.reason_code for reason in draft.reason_codes]


def test_blocked_packet_not_requestable_or_blocked(tmp_path):
    execution, evaluation, decision, plan = _eligible_subject(tmp_path)
    blocked_packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record={**execution, "redaction": {"secrets_included": True}},
        plan=plan,
    )

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(
        blocked_packet,
        "allow_sandbox_replay",
    )

    assert draft.status == "blocked"
    assert "packet_blocked_from_review" in [reason.reason_code for reason in draft.reason_codes]
    assert "unsafe_redaction" in [reason.reason_code for reason in draft.reason_codes]


def test_missing_requested_action_not_requestable(tmp_path):
    packet = _ready_packet(tmp_path)

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(
        packet,
        "allow_read_only_agent_consumption",
    )

    assert draft.status == "not_requestable"
    assert "action_not_allowed_by_packet" in [reason.reason_code for reason in draft.reason_codes]


def test_safe_action_mapping_for_packet_actions(tmp_path):
    packet = _ready_packet(tmp_path)
    builder = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z")

    replay = builder.build(packet, "allow_sandbox_replay")
    prepare = builder.build(packet, "allow_prepare_approval_request")

    assert replay.status == "draft"
    assert replay.requested_action_kind == "sandbox_replay"
    assert prepare.status == "draft"
    assert prepare.requested_action_kind == "prepare_approval_request"
    assert builder.available_actions(packet) == ("manual_review", "prepare_approval_request", "sandbox_replay")


def test_missing_required_decision_packet_is_blocked_by_packet_builder_then_not_requestable(tmp_path):
    packet = ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        None,
        policy=ReviewPacketPolicy(require_decision=False),
    )

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")

    assert draft.status in {"blocked", "not_requestable"}
    assert "action_not_allowed_by_packet" in [reason.reason_code for reason in draft.reason_codes]
