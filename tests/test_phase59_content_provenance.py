from __future__ import annotations

import inspect
from pathlib import Path

from channels.youtube.transport import FakeYouTubeTransport
from src.core.content.models import ContentCompleteness
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.runtime.events import EventEnvelope
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from youtube_video_read_handler import YOUTUBE_VIDEO_READ_CAPABILITY, YouTubeVideoReadHandler


def _make_ctx(event: EventEnvelope) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec_flow_999",
        deployment_id="dep-001",
        trigger_event=event,
    )


def test_end_to_end_event_read_ingestion_and_provenance_lineage():
    # 1. Event: YouTube video published event received
    event = EventEnvelope(
        event_id="evt_yt_pub_123",
        event_type="youtube.video.published",
        source="youtube-data-api-uploads",
        payload={"video_id": "vid-provenance-001", "channel_id": "channel-test"},
        occurred_at="2026-08-10T02:00:00Z",
    )

    # 2. Capability: youtube.video.read executed via handler
    transport = FakeYouTubeTransport()
    transport.videos_by_id["vid-provenance-001"] = {
        "id": "vid-provenance-001",
        "snippet": {
            "title": "Provenance Video Title",
            "description": "Provenance Video Description",
            "channelId": "channel-test",
            "publishedAt": "2026-08-10T02:00:00Z",
        },
        "contentDetails": {"duration": "PT10M"},
        "status": {"privacyStatus": "public"},
    }

    handler = YouTubeVideoReadHandler(transport=transport, access_token_resolver=lambda _: "token")
    ctx = _make_ctx(event)
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    read_result = handler.execute(
        context=ctx,
        node=node,
        resolved_node=resolved,
        input_data={"video_id": event.payload["video_id"]},
    )
    assert read_result["found"] is True

    # 3. Snapshot & Provenance Construction
    snapshot = ExternalResourceSnapshot.from_dict(read_result["snapshot"])

    provenance = {
        "component_id": event.source,
        "execution_id": ctx.execution_id,
        "install_id": resolved.install_id,
        "observed_at": snapshot.observed_at,
        "source_event_id": event.event_id,
        "workspace_id": "ws-001",
    }

    # 4. Content Repository Ingestion
    repo = InMemoryContentRepository()
    item, rev, created = repo.upsert_external_resource(snapshot=snapshot, provenance=provenance)

    assert created is True
    assert item.title == "Provenance Video Title"
    assert item.body == "Provenance Video Description"
    assert item.primary_source_ref == "youtube:video:vid-provenance-001"
    assert item.source_provenance["source_event_id"] == "evt_yt_pub_123"
    assert item.source_provenance["execution_id"] == "exec_flow_999"
    assert rev.source_provenance["source_event_id"] == "evt_yt_pub_123"


def test_no_transcript_falsely_claimed_assertion():
    event = EventEnvelope(
        event_id="evt-dummy",
        event_type="youtube.video.published",
        source="youtube-data-api-uploads",
        payload={"video_id": "vid-101"},
        occurred_at="2026-08-10T00:00:00Z",
    )
    transport = FakeYouTubeTransport()
    handler = YouTubeVideoReadHandler(transport=transport, access_token_resolver=lambda _: "tok")
    ctx = _make_ctx(event)
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    read_result = handler.execute(
        context=ctx,
        node=node,
        resolved_node=resolved,
        input_data={"video_id": "vid-101"},
    )

    # Explicit assertion: youtube.video.read provides METADATA_ONLY completeness
    assert read_result["completeness"] == ContentCompleteness.METADATA_ONLY.value
    assert "transcript" not in read_result
    assert "transcript" not in read_result.get("snapshot", {}).get("fields", {})


def test_generic_core_neutrality_no_provider_branches():
    import src.core.content.repository as repo_mod
    import src.core.content.resources as res_mod

    res_src = inspect.getsource(res_mod)
    repo_src = inspect.getsource(repo_mod)

    assert 'if provider == "youtube"' not in res_src
    assert 'if provider == "youtube"' not in repo_src
    assert 'if self.provider == "youtube"' not in res_src
    assert 'if self.provider == "youtube"' not in repo_src
