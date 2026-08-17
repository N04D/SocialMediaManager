from __future__ import annotations

from src.core.runtime import ApprovalRequestDraftBuilder, ApprovalStore

from tests.test_phase70_approval_request_contract import _ready_packet


def _draft(tmp_path, *, clock="2026-08-17T12:00:00Z", action="allow_manual_review"):
    return ApprovalRequestDraftBuilder(clock=lambda: clock).build(_ready_packet(tmp_path), action)


def _stable(payload):
    cleaned = dict(payload)
    cleaned.pop("approval_id", None)
    cleaned.pop("created_at", None)
    cleaned.pop("updated_at", None)
    cleaned["audit_events"] = [
        {key: value for key, value in event.items() if key not in {"event_id", "approval_id", "timestamp"}}
        for event in cleaned.get("audit_events", [])
    ]
    return cleaned


def test_same_draft_and_actor_stable_excluding_volatile_fields(tmp_path):
    draft = _draft(tmp_path)

    first = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft, actor="operator")
    second = ApprovalStore(clock=lambda: "2026-08-17T14:00:00Z").create_from_draft(draft, actor="operator")

    assert _stable(first.to_dict()) == _stable(second.to_dict())
    assert first.approval_id != second.approval_id
    assert first.created_at != second.created_at


def test_list_ordering_is_stable(tmp_path):
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _draft(first_dir, clock="2026-08-17T12:00:00Z")
    second = _draft(second_dir, clock="2026-08-17T12:01:00Z", action="allow_sandbox_replay")
    store = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z")
    first_request = store.create_from_draft(first)
    store.clock = lambda: "2026-08-17T13:01:00Z"
    second_request = store.create_from_draft(second)

    assert [item.approval_id for item in store.list()] == [first_request.approval_id, second_request.approval_id]


def test_audit_ordering_is_stable(tmp_path):
    store = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z")
    approval = store.create_from_draft(_draft(tmp_path))
    store.clock = lambda: "2026-08-17T13:05:00Z"
    store.approve(approval.approval_id, reviewer_id="reviewer")
    store.clock = lambda: "2026-08-17T13:06:00Z"
    store.reject(approval.approval_id, reviewer_id="reviewer")

    events = store.audit_events(approval.approval_id)

    assert [event.event_type for event in events] == ["created", "approved", "invalid_transition_attempted"]
    assert [event.timestamp for event in events] == sorted(event.timestamp for event in events)


def test_reason_codes_required_reviews_and_scope_are_sorted(tmp_path):
    draft = _draft(tmp_path).to_dict()
    draft["required_reviews"] = ["z", "manual_review", "a"]
    draft["scope"] = {"z": "z", "a": "a", "packet_id": "packet"}

    approval = ApprovalStore(clock=lambda: "2026-08-17T13:00:00Z").create_from_draft(draft)
    payload = approval.to_dict()

    assert list(payload["required_reviews"]) == ["a", "manual_review", "z"]
    assert list(payload["scope"].keys()) == sorted(payload["scope"].keys())
    assert [reason["reason_code"] for reason in payload["reason_codes"]] == sorted(
        reason["reason_code"] for reason in payload["reason_codes"]
    )
