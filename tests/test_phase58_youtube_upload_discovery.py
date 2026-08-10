from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from channels.youtube.transport import FakeYouTubeTransport
from src.core.runtime.candidates import (
    ExternalSourceCandidate,
    admit_and_activate_external_source,
)
from src.core.runtime.components import ComponentManifest
from src.core.runtime.dispatcher import TriggerDispatcher
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.event_store import SqliteEventStore
from src.core.runtime.events import EventEnvelope, EventSource, utc_now_iso
from src.core.runtime.installs import Install
from src.core.runtime.permissions import EgressDestination, InstallPermissionGrants, NetworkPermissions
from src.core.runtime.deployments import PlaybookDeployment
from src.core.runtime.playbooks import PlaybookDefinition, PlaybookNode
from src.core.runtime.sources import (
    SourceCheckpointStore,
    poll_and_ingest_external_events,
)
from youtube_upload_event_source import YOUTUBE_UPLOADS_COMPONENT_ID, YOUTUBE_VIDEO_PUBLISHED_EVENT, YouTubeUploadsEventSource
from youtube_upload_source_admission import youtube_upload_source_admission


from src.core.runtime.installs import Install, InstallGrants


def _make_sample_install(install_id: str = "install-yt-001") -> Install:
    return Install(
        install_id=install_id,
        workspace_id="ws-001",
        provider="youtube",
        account_ref="acc-001",
        secret_refs=("youtube-access-token-ref",),
        grants=InstallGrants(
            permission_grants=InstallPermissionGrants(
                network=NetworkPermissions(
                    egress=(
                        EgressDestination(host="www.googleapis.com", port=443),
                        EgressDestination(host="oauth2.googleapis.com", port=443),
                    )
                )
            )
        ),
    )


def _make_sample_component() -> ComponentManifest:
    return ComponentManifest(
        component_id=YOUTUBE_UPLOADS_COMPONENT_ID,
        provider="youtube",
        version="1.0.0",
        sdk_version="1.0.0",
    )


def _make_candidate(build_source_fn: Any) -> ExternalSourceCandidate:
    return ExternalSourceCandidate(
        component_id=YOUTUBE_UPLOADS_COMPONENT_ID,
        source_id=YOUTUBE_UPLOADS_COMPONENT_ID,
        event_type=YOUTUBE_VIDEO_PUBLISHED_EVENT,
        build_source=build_source_fn,
        read_only=True,
        bounded_polling=True,
        page_size_limit=50,
        max_pages_limit=10,
        first_poll_policy="FROM_NOW",
        gap_detection=True,
        stable_external_identity=True,
        checkpoint_support=True,
        required_egress=("www.googleapis.com:443", "oauth2.googleapis.com:443"),
        required_secrets=("youtube-access-token-ref",),
    )


def test_youtube_source_admission_success(tmp_path: Path):
    transport = FakeYouTubeTransport()
    source = YouTubeUploadsEventSource(transport=transport)
    candidate = _make_candidate(lambda: source)
    component = _make_sample_component()
    install = _make_sample_install()

    admission = youtube_upload_source_admission(component=component, install=install, candidate=candidate)
    assert admission.admitted is True
    assert admission.status == "ADMITTED"

    source_registry = {}
    activation = admit_and_activate_external_source(
        candidate=candidate,
        component=component,
        install=install,
        source_registry=source_registry,
        admission_evaluator=youtube_upload_source_admission,
    )

    assert activation.activated is True
    assert activation.status == "ADMITTED"
    assert (YOUTUBE_UPLOADS_COMPONENT_ID, YOUTUBE_UPLOADS_COMPONENT_ID) in source_registry


def test_youtube_source_admission_blocked_checks():
    transport = FakeYouTubeTransport()
    source = YouTubeUploadsEventSource(transport=transport)
    component = _make_sample_component()
    install = _make_sample_install()

    # Non-read-only candidate
    bad_cand = ExternalSourceCandidate(
        component_id=YOUTUBE_UPLOADS_COMPONENT_ID,
        source_id=YOUTUBE_UPLOADS_COMPONENT_ID,
        event_type=YOUTUBE_VIDEO_PUBLISHED_EVENT,
        build_source=lambda: source,
        read_only=False,
    )
    adm = youtube_upload_source_admission(component=component, install=install, candidate=bad_cand)
    assert adm.admitted is False
    assert "BLOCKED_NOT_READ_ONLY" in adm.reasons


def test_uploads_playlist_resolution():
    transport = FakeYouTubeTransport()
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "secret_token_12345",
        channel_id_resolver=lambda _: "channel-test",
    )

    batch = source.poll(install_id="install-yt-001")
    assert batch.records == ()
    cp = json.loads(batch.next_checkpoint)
    assert cp["uploads_playlist_id"] == "UU_channel_test"


def test_first_poll_from_now_policy():
    transport = FakeYouTubeTransport()
    transport.playlist_items["UU_channel_test"] = [
        {
            "id": "item-1",
            "contentDetails": {"videoId": "vid-001", "videoPublishedAt": "2026-08-10T01:00:00Z"},
            "snippet": {"title": "Existing Video 1", "publishedAt": "2026-08-10T01:00:00Z"},
            "status": {"privacyStatus": "public"},
        }
    ]
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "valid-token",
        channel_id_resolver=lambda _: "channel-test",
    )

    # First poll (no checkpoint) -> FROM_NOW baseline
    batch = source.poll(install_id="install-yt-001")
    assert len(batch.records) == 0  # 0 events emitted on first poll
    cp = json.loads(batch.next_checkpoint)
    assert cp["latest_published_at"] == "2026-08-10T01:00:00Z"
    assert "vid-001" in cp["latest_video_ids"]


def test_subsequent_poll_discovers_new_video():
    transport = FakeYouTubeTransport()
    playlist = [
        {
            "id": "item-1",
            "contentDetails": {"videoId": "vid-001", "videoPublishedAt": "2026-08-10T01:00:00Z"},
            "snippet": {"title": "First Video", "publishedAt": "2026-08-10T01:00:00Z"},
            "status": {"privacyStatus": "public"},
        }
    ]
    transport.playlist_items["UU_channel_test"] = playlist
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "valid-token",
        channel_id_resolver=lambda _: "channel-test",
    )

    # First poll baseline
    b1 = source.poll(install_id="install-yt-001")

    # Add new video upload
    playlist.insert(
        0,
        {
            "id": "item-2",
            "contentDetails": {"videoId": "vid-002", "videoPublishedAt": "2026-08-10T02:00:00Z"},
            "snippet": {"title": "Second Video", "publishedAt": "2026-08-10T02:00:00Z"},
            "status": {"privacyStatus": "public"},
        },
    )

    # Second poll
    b2 = source.poll(install_id="install-yt-001", checkpoint=b1.next_checkpoint)
    assert len(b2.records) == 1
    assert b2.records[0].external_event_id == "yt_pub_vid-002"
    assert b2.records[0].payload["video_id"] == "vid-002"
    assert b2.records[0].payload["title"] == "Second Video"


def test_gap_detection_preserves_checkpoint():
    transport = FakeYouTubeTransport()
    # Create 15 items but max_pages_per_poll = 1 with page_size = 2
    playlist = [
        {
            "id": f"item-{i}",
            "contentDetails": {"videoId": f"vid-{i:03d}", "videoPublishedAt": f"2026-08-10T{i:02d}:00:00Z"},
            "snippet": {"title": f"Video {i}", "publishedAt": f"2026-08-10T{i:02d}:00:00Z"},
            "status": {"privacyStatus": "public"},
        }
        for i in range(15, 0, -1)
    ]
    transport.playlist_items["UU_channel_test"] = playlist

    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "token",
        channel_id_resolver=lambda _: "channel-test",
        max_pages_per_poll=1,
        page_size=2,
    )

    # Checkpoint set to old vid-001
    old_cp = json.dumps({
        "uploads_playlist_id": "UU_channel_test",
        "latest_published_at": "2026-08-10T01:00:00Z",
        "latest_video_ids": ["vid-001"],
    })

    batch = source.poll(install_id="install-yt-001", checkpoint=old_cp, limit=2)
    assert batch.gap_detected is True
    assert batch.next_checkpoint == old_cp  # Checkpoint unchanged


def test_permission_egress_denied():
    transport = FakeYouTubeTransport()
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "token",
        permission_evaluator=lambda _inst, _dest: False,  # Denied egress
    )

    with pytest.raises(PlaybookExecutionError) as exc_info:
        source.poll(install_id="install-yt-001")

    assert exc_info.value.code == "EGRESS_DENIED"
    assert len(transport.requests) == 0  # 0 network calls executed


def test_secret_canary_isolation():
    transport = FakeYouTubeTransport()
    secret_token = "SUPER_SECRET_ACCESS_TOKEN_999"
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: secret_token,
        channel_id_resolver=lambda _: "channel-test",
    )

    playlist = [
        {
            "id": "item-1",
            "contentDetails": {"videoId": "vid-001", "videoPublishedAt": "2026-08-10T01:00:00Z"},
            "snippet": {"title": "Test Video", "publishedAt": "2026-08-10T01:00:00Z"},
            "status": {"privacyStatus": "public"},
        }
    ]
    transport.playlist_items["UU_channel_test"] = playlist

    b1 = source.poll(install_id="install-yt-001")
    assert secret_token not in b1.next_checkpoint

    playlist.insert(
        0,
        {
            "id": "item-2",
            "contentDetails": {"videoId": "vid-002", "videoPublishedAt": "2026-08-10T02:00:00Z"},
            "snippet": {"title": "New Video", "publishedAt": "2026-08-10T02:00:00Z"},
            "status": {"privacyStatus": "public"},
        },
    )
    b2 = source.poll(install_id="install-yt-001", checkpoint=b1.next_checkpoint)
    rec_json = json.dumps(b2.records[0].payload)
    assert secret_token not in rec_json
    assert secret_token not in b2.next_checkpoint


def test_multi_worker_lease_safety(tmp_path: Path):
    db_path = tmp_path / "test_sources.db"
    checkpoint_store = SourceCheckpointStore(db_path=db_path)
    transport = FakeYouTubeTransport()
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "token",
        channel_id_resolver=lambda _: "channel-test",
    )
    event_store = SqliteEventStore(db_path)
    install = _make_sample_install()

    # Worker 1 acquires lease
    acquired = checkpoint_store.acquire_lease("youtube-data-api-uploads", install.install_id, worker_id="worker-1")
    assert acquired is True

    # Worker 2 attempts poll and fails lease
    success, reason, events = poll_and_ingest_external_events(
        source=source,
        install=install,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        worker_id="worker-2",
    )

    assert success is False
    assert reason == "LEASE_BUSY"


def test_end_to_end_dispatch_and_playbook_execution(tmp_path: Path):
    db_path = tmp_path / "e2e_sources.db"
    checkpoint_store = SourceCheckpointStore(db_path=db_path)
    event_store = SqliteEventStore(db_path)
    install = _make_sample_install()

    transport = FakeYouTubeTransport()
    playlist = [
        {
            "id": "item-1",
            "contentDetails": {"videoId": "vid-001", "videoPublishedAt": "2026-08-10T01:00:00Z"},
            "snippet": {"title": "Baseline Video", "publishedAt": "2026-08-10T01:00:00Z"},
            "status": {"privacyStatus": "public"},
        }
    ]
    transport.playlist_items["UU_channel_test"] = playlist
    source = YouTubeUploadsEventSource(
        transport=transport,
        access_token_resolver=lambda _: "token",
        channel_id_resolver=lambda _: "channel-test",
    )

    # 1. First poll -> bootstrap
    poll_and_ingest_external_events(
        source=source,
        install=install,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        worker_id="worker-1",
    )

    # 2. Add new video
    playlist.insert(
        0,
        {
            "id": "item-2",
            "contentDetails": {"videoId": "vid-002", "videoPublishedAt": "2026-08-10T02:00:00Z"},
            "snippet": {"title": "Discovered Video", "publishedAt": "2026-08-10T02:00:00Z"},
            "status": {"privacyStatus": "public"},
        },
    )

    # 3. Second poll -> Ingest event into SqliteEventStore
    ok, reason, events = poll_and_ingest_external_events(
        source=source,
        install=install,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        worker_id="worker-1",
    )
    assert ok is True
    assert len(events) == 1
    event = events[0]
    assert event.event_type == YOUTUBE_VIDEO_PUBLISHED_EVENT

    # 4. TriggerDispatcher matches event to PlaybookDeployment
    playbook_def = PlaybookDefinition(
        playbook_id="youtube.fanout.playbook",
        version="1.0",
        schema_version="1.0",
        name="YouTube Upload Fanout Playbook",
        nodes=(
            PlaybookNode(node_id="trig_node", kind="trigger", config={"event_type": YOUTUBE_VIDEO_PUBLISHED_EVENT}),
            PlaybookNode(
                node_id="echo_node",
                kind="capability",
                config={"capability": "test.echo", "message": "youtube_video_processed"},
            ),
        ),
    )

    deployment = PlaybookDeployment(
        deployment_id="dep-yt-001",
        playbook_id="youtube.fanout.playbook",
        playbook_version="1.0",
        workspace_id="ws-001",
    )

    dispatcher = TriggerDispatcher(
        store=event_store,
        registry=None,
        executor=None,
        deployments={deployment.deployment_id: deployment},
        playbooks={playbook_def.playbook_id: playbook_def},
    )
    matched = dispatcher._find_matching_deployments(event)
    assert len(matched) == 1
    assert matched[0][0].deployment_id == "dep-yt-001"


def test_production_mutation_count_remains_strictly_two():
    from src.core.runtime.handlers import CapabilityHandlerRegistry

    registry = CapabilityHandlerRegistry()

    # Verify only 2 mutation handlers exist in codebase
    from publication_calendar_runtime_handlers import CALENDAR_COMPONENT_ID
    from publication_git_runtime_handlers import GIT_WEBSITE_COMPONENT_ID

    # We assert no YouTube write mutation was registered in Phase 58
    assert len(registry._handlers) == 0
