from __future__ import annotations

import pytest

from channels.youtube.transport import FakeYouTubeTransport
from src.core.content.models import ContentCompleteness
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.events import EventEnvelope
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import Install, InstallGrants
from src.core.runtime.permissions import EgressDestination, InstallPermissionGrants, NetworkPermissions
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from youtube_video_read_admission import (
    YouTubeReadCapabilityCandidate,
    admit_and_register_youtube_read_capability,
    evaluate_youtube_read_capability_admission,
)
from youtube_video_read_handler import YOUTUBE_UPLOADS_COMPONENT_ID, YOUTUBE_VIDEO_READ_CAPABILITY, YouTubeVideoReadHandler


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
                    egress=(EgressDestination(host="www.googleapis.com", port=443),)
                )
            )
        ),
    )


def _make_ctx() -> ExecutionContext:
    evt = EventEnvelope(
        event_id="evt-001",
        event_type="youtube.video.published",
        source="youtube-data-api-uploads",
        payload={"video_id": "vid-100"},
        occurred_at="2026-08-10T00:00:00Z",
    )
    return ExecutionContext(
        execution_id="exec-001",
        deployment_id="dep-001",
        trigger_event=evt,
    )


def test_youtube_read_capability_admission_success():
    install = _make_sample_install()
    candidate = YouTubeReadCapabilityCandidate()
    ok, reasons = evaluate_youtube_read_capability_admission(candidate, install=install)
    assert ok is True
    assert len(reasons) == 0


def test_youtube_read_capability_admission_blocked_checks():
    install_no_egress = Install(
        install_id="install-no-egress",
        workspace_id="ws-001",
        provider="youtube",
        account_ref="acc-001",
        secret_refs=("youtube-access-token-ref",),
        grants=InstallGrants(permission_grants=InstallPermissionGrants(network=NetworkPermissions(egress=()))),
    )
    candidate = YouTubeReadCapabilityCandidate()
    ok, reasons = evaluate_youtube_read_capability_admission(candidate, install=install_no_egress)
    assert ok is False
    assert any("BLOCKED_REQUIRED_EGRESS_DENIED" in r for r in reasons)


def test_youtube_video_read_handler_success():
    transport = FakeYouTubeTransport()
    handler = YouTubeVideoReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "token-123",
    )
    registry = CapabilityHandlerRegistry()
    install = _make_sample_install()
    ok, reasons = admit_and_register_youtube_read_capability(registry, handler, install=install)
    assert ok is True

    ctx = _make_ctx()
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    res = handler.execute(context=ctx, node=node, resolved_node=resolved, input_data={"video_id": "vid-100"})
    assert res["found"] is True
    assert res["video_id"] == "vid-100"
    assert res["resource_ref"] == "youtube:video:vid-100"
    assert res["completeness"] == ContentCompleteness.METADATA_ONLY.value
    assert "snapshot" in res


def test_youtube_video_read_handler_missing_video():
    transport = FakeYouTubeTransport()
    transport.videos_by_id["vid-missing"] = None
    handler = YouTubeVideoReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "token-123",
    )
    ctx = _make_ctx()
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    res = handler.execute(context=ctx, node=node, resolved_node=resolved, input_data={"video_id": "vid-missing"})
    assert res["found"] is False
    assert res["status"] == "missing_or_unavailable"
    assert res["video_id"] == "vid-missing"


def test_youtube_video_read_handler_secret_canary_isolation():
    transport = FakeYouTubeTransport()
    handler = YouTubeVideoReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "secret-token-canary-999",
    )
    ctx = _make_ctx()
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    with pytest.raises(PlaybookExecutionError):
        handler.execute(
            context=ctx,
            node=node,
            resolved_node=resolved,
            input_data={"video_id": "vid-100", "access_token": "secret-token-canary-999"},
        )


def test_youtube_video_read_handler_missing_video_id_input():
    transport = FakeYouTubeTransport()
    handler = YouTubeVideoReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "token-123",
    )
    ctx = _make_ctx()
    node = PlaybookNode(node_id="read_node", kind="capability", config={"capability": YOUTUBE_VIDEO_READ_CAPABILITY})
    resolved = ExecutionPlanNode(node_id="read_node", kind="capability", install_id="install-yt-001")

    with pytest.raises(PlaybookExecutionError) as exc_info:
        handler.execute(context=ctx, node=node, resolved_node=resolved, input_data={})
    assert exc_info.value.code == "MISSING_REQUIRED_INPUT"


def test_youtube_video_read_is_read_only_and_mutation_count_unchanged():
    registry = CapabilityHandlerRegistry()
    transport = FakeYouTubeTransport()
    handler = YouTubeVideoReadHandler(transport=transport, access_token_resolver=lambda _: "tok")
    admit_and_register_youtube_read_capability(registry, handler)

    assert (YOUTUBE_UPLOADS_COMPONENT_ID, YOUTUBE_VIDEO_READ_CAPABILITY) in registry._handlers
    assert len(registry._handlers) == 1
