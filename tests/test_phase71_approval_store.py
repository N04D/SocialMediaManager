from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ApprovalRequestDraftPolicy, ApprovalStore

from tests.test_phase70_approval_request_contract import _ready_packet


def _approval(tmp_path, *, expires: int | None = None):
    packet = _ready_packet(tmp_path)
    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:00:00Z").build(
        packet,
        "allow_manual_review",
        policy=ApprovalRequestDraftPolicy(default_expiration_hours=expires),
    )
    store = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z")
    return store, store.create_from_draft(draft)


def test_pending_approve_transition(tmp_path):
    store, approval = _approval(tmp_path)

    result = store.approve(approval.approval_id, reviewer_id="reviewer-1", reason="looks good")

    assert result.changed is True
    assert result.status == "approved"
    assert result.approval.status == "approved"
    assert result.approval.decision.decision == "approve"
    assert result.approval.decided_by == "reviewer-1"
    assert result.approval.audit_events[-1].event_type == "approved"


def test_pending_reject_transition(tmp_path):
    store, approval = _approval(tmp_path)

    result = store.reject(approval.approval_id, reviewer_id="reviewer-1", reason="no")

    assert result.status == "rejected"
    assert result.approval.decision.decision == "reject"
    assert result.approval.audit_events[-1].event_type == "rejected"


def test_pending_cancel_transition(tmp_path):
    store, approval = _approval(tmp_path)

    result = store.cancel(approval.approval_id, actor="operator-1", reason="superseded")

    assert result.status == "cancelled"
    assert result.approval.decision.decision == "cancel"
    assert result.approval.audit_events[-1].event_type == "cancelled"


def test_pending_expire_transition(tmp_path):
    store, approval = _approval(tmp_path, expires=1)

    result = store.expire(approval.approval_id, now="2026-08-17T13:30:00Z")

    assert result.changed is True
    assert result.status == "expired"
    assert result.approval.decision.decision == "expire"
    assert result.approval.audit_events[-1].event_type == "expired"


def test_terminal_states_reject_further_transitions_without_status_mutation(tmp_path):
    store, approval = _approval(tmp_path)
    approved = store.approve(approval.approval_id, reviewer_id="reviewer-1").approval

    result = store.reject(approved.approval_id, reviewer_id="reviewer-2")

    assert result.changed is False
    assert result.status == "approved"
    assert result.approval.status == "approved"
    assert result.approval.audit_events[-1].event_type == "invalid_transition_attempted"
    assert result.approval.audit_events[-1].reason_code == "invalid_transition_attempted"


def test_invalid_transition_does_not_mutate_decision(tmp_path):
    store, approval = _approval(tmp_path)
    rejected = store.reject(approval.approval_id, reviewer_id="reviewer-1", reason="done").approval

    result = store.approve(rejected.approval_id, reviewer_id="reviewer-2")

    assert result.changed is False
    assert result.approval.status == "rejected"
    assert result.approval.decision == rejected.decision
    assert result.approval.updated_at == rejected.updated_at


def test_pending_not_expired_before_expires_at(tmp_path):
    store, approval = _approval(tmp_path, expires=2)

    result = store.expire(approval.approval_id, now="2026-08-17T13:00:00Z")

    assert result.changed is False
    assert result.status == "pending"
    assert result.reason_code == "not_expired"


def test_approved_does_not_expire(tmp_path):
    store, approval = _approval(tmp_path, expires=1)
    approved = store.approve(approval.approval_id, reviewer_id="reviewer-1").approval

    result = store.expire(approved.approval_id, now="2026-08-17T14:00:00Z")

    assert result.changed is False
    assert result.status == "approved"
    assert result.approval.decision.decision == "approve"


def test_get_list_and_filter_results(tmp_path):
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first_store, first = _approval(first_dir)
    second_packet = _ready_packet(second_dir)
    second_draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:01:00Z").build(
        second_packet,
        "allow_sandbox_replay",
    )
    first_store.clock = lambda: "2026-08-17T13:01:00Z"
    second = first_store.create_from_draft(second_draft)
    first_store.approve(first.approval_id, reviewer_id="reviewer")

    assert first_store.get(first.approval_id).status == "approved"
    assert [item.approval_id for item in first_store.list()] == [first.approval_id, second.approval_id]
    assert first_store.list(status="pending") == (second,)
    assert first_store.list(requested_action_kind="sandbox_replay") == (second,)
