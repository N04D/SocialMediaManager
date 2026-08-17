from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ManualReviewPacketBuilder

from tests.test_phase69_manual_review_packet import _needs_review_subject


def _ready_packet(tmp_path):
    execution, evaluation, decision, plan = _needs_review_subject(tmp_path)
    return ManualReviewPacketBuilder(clock=lambda: "2026-08-17T10:00:00Z").build(
        decision,
        evaluation=evaluation,
        execution_record=execution,
        plan=plan,
    )


def _stable(payload):
    cleaned = dict(payload)
    cleaned.pop("draft_id", None)
    cleaned.pop("created_at", None)
    cleaned.pop("expires_at", None)
    return cleaned


def test_same_inputs_stable_excluding_volatile_fields(tmp_path):
    packet = _ready_packet(tmp_path)
    first = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")
    second = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:00:00Z").build(packet, "allow_manual_review")

    assert _stable(first.to_dict()) == _stable(second.to_dict())
    assert first.draft_id != second.draft_id
    assert first.created_at != second.created_at


def test_ordering_is_stable(tmp_path):
    packet = _ready_packet(tmp_path).to_dict()
    packet["required_reviews"] = ["z_review", "manual_review", "a_review"]
    packet["safe_next_actions"] = list(reversed(packet["safe_next_actions"]))

    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T11:00:00Z").build(packet, "allow_manual_review")
    payload = draft.to_dict()

    assert list(payload["required_reviews"]) == ["a_review", "manual_review", "z_review"]
    assert list(payload["scope"].keys()) == sorted(payload["scope"].keys())
    assert list(payload["safety_summary"].keys()) == sorted(payload["safety_summary"].keys())
    assert [reason["reason_code"] for reason in payload["reason_codes"]] == sorted(
        reason["reason_code"] for reason in payload["reason_codes"]
    )
