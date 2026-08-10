from pathlib import Path
import pytest

from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.event_store import EventDeliveryState, InMemoryEventStore, SqliteEventStore


def test_in_memory_event_store_append_and_get():
    store = InMemoryEventStore()
    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event = EventEnvelope(
        event_id="evt_test001",
        event_type="website.article.published",
        source=source,
        payload={"commit_sha": "abc1234"},
        idempotency_key="evt_idempotency_001",
    )

    appended = store.append(event)
    assert appended.event_id == "evt_test001"

    # Duplicate append by idempotency_key returns original
    event_dup = EventEnvelope(
        event_id="evt_test002",
        event_type="website.article.published",
        source=source,
        payload={"commit_sha": "abc1234"},
        idempotency_key="evt_idempotency_001",
    )
    dup_appended = store.append(event_dup)
    assert dup_appended.event_id == "evt_test001"


def test_sqlite_event_store_concurrency_and_claims(tmp_path: Path):
    db_path = tmp_path / "events.db"
    store1 = SqliteEventStore(db_path)
    store2 = SqliteEventStore(db_path)

    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event1 = EventEnvelope(event_id="evt_s1", event_type="website.article.published", source=source)
    event2 = EventEnvelope(event_id="evt_s2", event_type="website.article.published", source=source)

    store1.append(event1)
    store1.append(event2)

    # Worker 1 claims pending events
    claimed1 = store1.claim_pending(owner="worker_1", limit=1)
    assert len(claimed1) == 1
    assert claimed1[0].event_id == "evt_s1"

    # Worker 2 claims next pending event
    claimed2 = store2.claim_pending(owner="worker_2", limit=1)
    assert len(claimed2) == 1
    assert claimed2[0].event_id == "evt_s2"

    # No more pending events
    claimed3 = store1.claim_pending(owner="worker_1", limit=1)
    assert len(claimed3) == 0


def test_sqlite_event_store_dispatch_records(tmp_path: Path):
    db_path = tmp_path / "events.db"
    store = SqliteEventStore(db_path)
    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event = EventEnvelope(event_id="evt_d1", event_type="website.article.published", source=source)

    store.append(event)
    store.record_dispatch_started(event_id="evt_d1", deployment_id="dep_A", owner="dispatcher")

    rec = store.get_dispatch_record("evt_d1", "dep_A")
    assert rec is not None
    assert rec.state == EventDeliveryState.CLAIMED.value
    assert rec.attempts == 1

    store.mark_dispatched("evt_d1", "dep_A", execution_id="exec_100")
    rec2 = store.get_dispatch_record("evt_d1", "dep_A")
    assert rec2 is not None
    assert rec2.state == EventDeliveryState.DISPATCHED.value
    assert rec2.execution_id == "exec_100"

    # Mark failed for another deployment
    store.record_dispatch_started("evt_d1", "dep_B", owner="dispatcher")
    store.mark_failed("evt_d1", "dep_B", error_code="TEST_FAILURE", error_message="Deployment B failed.")

    rec_b = store.get_dispatch_record("evt_d1", "dep_B")
    assert rec_b is not None
    assert rec_b.state == EventDeliveryState.FAILED.value
    assert rec_b.error_code == "TEST_FAILURE"


def test_secret_boundary_in_event_envelope():
    source = EventSource(component="github-markdown-website", provider="github")

    with pytest.raises(ValueError, match="secret-shaped"):
        EventEnvelope(
            event_id="evt_sec1",
            event_type="website.article.published",
            source=source,
            payload={"secret_token": "supersecret123"},
        )

    with pytest.raises(ValueError, match="secret-shaped"):
        EventEnvelope(
            event_id="evt_sec2",
            event_type="website.article.published",
            source=source,
            metadata={"api_key": "key_xyz"},
        )
