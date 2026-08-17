from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ApprovalRequestDraftPolicy, ApprovalStore

from tests.test_phase70_approval_request_contract import _informational_packet, _ready_packet


def _draft(tmp_path, *, clock: str = "2026-08-17T12:00:00Z", expires: int | None = None):
    packet = _ready_packet(tmp_path)
    return ApprovalRequestDraftBuilder(clock=lambda: clock).build(
        packet,
        "allow_manual_review",
        policy=ApprovalRequestDraftPolicy(default_expiration_hours=expires),
    )


def test_draft_creates_pending_approval_request(tmp_path):
    draft = _draft(tmp_path)
    store = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z")

    approval = store.create_from_draft(draft, actor="operator-1")

    assert approval.status == "pending"
    assert approval.draft_id == draft.draft_id
    assert approval.packet_id == draft.packet_id
    assert approval.requested_action == draft.requested_action
    assert approval.requested_action_kind == "manual_review"
    assert approval.reviewer_role == "human_reviewer"
    assert approval.scope == draft.scope
    assert approval.audit_events[0].event_type == "created"
    assert approval.audit_events[0].actor == "operator-1"


def test_not_requestable_draft_becomes_blocked_request(tmp_path):
    packet = _informational_packet(tmp_path)
    draft = ApprovalRequestDraftBuilder(clock=lambda: "2026-08-17T12:00:00Z").build(
        packet,
        "allow_read_only_agent_consumption",
    )

    approval = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft)

    assert approval.status == "blocked"
    assert "draft_not_requestable" in [reason.reason_code for reason in approval.reason_codes]
    assert approval.audit_events[0].reason_code == "blocked"


def test_unsafe_action_kind_rejected(tmp_path):
    draft = _draft(tmp_path).to_dict()
    draft["requested_action_kind"] = "production_execute"

    approval = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft)

    assert approval.status == "blocked"
    assert "unsafe_requested_action_kind" in [reason.reason_code for reason in approval.reason_codes]


def test_scope_and_reviewer_role_preserved(tmp_path):
    draft = _draft(tmp_path).to_dict()
    draft["reviewer_role"] = "maintainer"
    draft["scope"] = {"z": "last", "packet_id": "packet-1", "execution_id": "execution-1"}

    approval = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft)

    assert approval.reviewer_role == "maintainer"
    assert list(approval.scope.keys()) == sorted(approval.scope.keys())
    assert approval.scope["packet_id"] == "packet-1"
