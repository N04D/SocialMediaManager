from __future__ import annotations

import inspect
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from channels.youtube.channel import YouTubeChannelService
from channels.youtube.errors import YouTubeChannelError
from channels.youtube.transport import HttpYouTubeTransport, YouTubeTransport
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime.capabilities import CapabilityMode
from src.core.runtime.deployments import PlaybookDeployment, RequirementBinding
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.plans import compile_execution_plan
from src.core.runtime.playbooks import PlaybookDefinition
from src.core.runtime.resolver import RuntimeRegistry
from src.core.runtime.tracing import trace_execution
from youtube_runtime_handlers import (
    YOUTUBE_REMOTE_COMPONENT_ID,
    YOUTUBE_VIDEO_METADATA_READ_CAPABILITY,
    register_youtube_runtime_handlers,
)


class MockHttpResponse:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: dict[str, object]):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> MockHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._payload if limit < 0 else self._payload[:limit]


def load_youtube_playbook() -> PlaybookDefinition:
    payload = json.loads(
        Path("tests/fixtures/playbooks/phase46_youtube_video_metadata.json").read_text(encoding="utf-8")
    )
    return PlaybookDefinition.from_dict(payload)


def youtube_deployment(install_id: str = "youtube-remote-test") -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="phase46-youtube-video-metadata",
        playbook_id="youtube.phase46.video-metadata",
        playbook_version="1.0.0",
        workspace_id="workspace-1",
        requirement_bindings={"youtube_source": RequirementBinding(install_id)},
    )


def youtube_registry(install_id: str = "youtube-remote-test") -> RuntimeRegistry:
    registry = phase41_runtime_registry()
    registry.register_install(
        Install(
            install_id=install_id,
            workspace_id="workspace-1",
            provider="youtube",
            account_ref="youtube:test-channel",
            component_bindings={
                YOUTUBE_VIDEO_METADATA_READ_CAPABILITY: ComponentBinding(YOUTUBE_REMOTE_COMPONENT_ID),
            },
            config={"channel_account_id": "youtube:test-channel", "access_token_ref": "youtube-access-token-ref"},
            secret_refs=("youtube-access-token-ref",),
        )
    )
    return registry


def youtube_event(payload: dict[str, object] | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type="youtube.video.metadata.requested",
        source=EventSource(component="phase46-test", provider="youtube"),
        workspace_id="workspace-1",
        correlation_id="phase46-correlation",
        trace_id="phase46-trace",
        idempotency_key="phase46-youtube-video-metadata",
        payload={"video_id": "abc123DEF45"} if payload is None else payload,
    )


def compile_youtube_plan(install_id: str = "youtube-remote-test"):
    return compile_execution_plan(load_youtube_playbook(), youtube_deployment(install_id), youtube_registry(install_id))


def read_video_records(executor: PlaybookExecutor, execution_id: str):
    return [node for node in executor.ledger.list_node_executions(execution_id) if node.node_id == "read-video"]


def test_youtube_remote_metadata_read_through_playbook_executor() -> None:
    transport = HttpYouTubeTransport(timeout=4.5)
    service = YouTubeChannelService(transport=transport)
    observed: list[dict[str, object]] = []

    def urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
        observed.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "timeout": timeout,
                "authorization_present": bool(request.headers.get("Authorization", "")),
            }
        )
        return MockHttpResponse(
            {
                "items": [
                    {
                        "id": "abc123DEF45",
                        "snippet": {
                            "title": "Remote metadata fixture",
                            "description": "Read-only provider data.",
                            "publishedAt": "2026-08-09T10:00:00Z",
                            "channelId": "channel-123",
                            "channelTitle": "Fixture Channel",
                        },
                        "status": {"privacyStatus": "public"},
                        "processingDetails": {"processingStatus": "succeeded"},
                    }
                ]
            }
        )

    handler_registry = CapabilityHandlerRegistry()
    handler = register_youtube_runtime_handlers(
        handler_registry,
        youtube_service=service,
        access_tokens_by_install_id={"youtube-remote-test": "phase46-fixture-credential"},
    )
    executor = PlaybookExecutor(handler_registry)

    with (
        patch("channels.youtube.transport.urllib.request.urlopen", side_effect=urlopen),
        patch.object(transport, "create_upload_session", side_effect=AssertionError("upload forbidden")) as create,
        patch.object(transport, "upload_chunk", side_effect=AssertionError("upload forbidden")) as upload,
        patch.object(transport, "query_upload_session", side_effect=AssertionError("upload query forbidden")) as query,
        patch.object(transport, "exchange_code", side_effect=AssertionError("oauth mutation forbidden")) as exchange,
        patch.object(
            transport, "refresh_access_token", side_effect=AssertionError("token refresh forbidden")
        ) as refresh,
        patch.object(transport, "get_channel", side_effect=AssertionError("unrelated read forbidden")) as channel,
        patch.object(socket, "socket", wraps=socket.socket) as socket_spy,
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")) as run,
    ):
        outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

    assert handler.component_id == YOUTUBE_REMOTE_COMPONENT_ID
    assert handler.capability_id == YOUTUBE_VIDEO_METADATA_READ_CAPABILITY
    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert outcome.context.node_outputs["read-video"] == {
        "channel_id": "channel-123",
        "channel_title": "Fixture Channel",
        "description": "Read-only provider data.",
        "privacy_status": "public",
        "processing_status": "succeeded",
        "published_at": "2026-08-09T10:00:00Z",
        "source": "youtube-upload-channel",
        "title": "Remote metadata fixture",
        "video_id": "abc123DEF45",
    }
    assert observed == [
        {
            "url": (
                "https://www.googleapis.com/youtube/v3/videos?part=status%2CprocessingDetails%2Csnippet&id=abc123DEF45"
            ),
            "method": "GET",
            "timeout": 4.5,
            "authorization_present": True,
        }
    ]
    assert socket_spy.call_count == 0
    for mutation in (create, upload, query, exchange, refresh, channel, run):
        mutation.assert_not_called()
    trace = trace_execution(executor.ledger, outcome.execution.execution_id).to_dict()
    read_node = next(node for node in trace["nodes"] if node["node_id"] == "read-video")
    assert read_node["metadata"] == {
        "capability": "youtube.video.metadata.read",
        "component_id": "youtube-upload-channel",
        "install_id": "youtube-remote-test",
        "kind": "capability",
        "provider": "youtube",
        "requirement": "youtube_source",
    }
    assert "phase46-fixture-credential" not in json.dumps(outcome.context.node_outputs, sort_keys=True)
    assert "phase46-fixture-credential" not in json.dumps(trace, sort_keys=True)


def test_youtube_playbook_is_portable_and_deployment_binds_install() -> None:
    playbook = load_youtube_playbook()
    payload = playbook.to_dict()

    assert "install_id" not in json.dumps(payload)
    plan = compile_youtube_plan()
    read_node = next(node for node in plan.nodes if node.node_id == "read-video")
    assert read_node.requirement == "youtube_source"
    assert read_node.install_id == "youtube-remote-test"
    assert read_node.component_id == YOUTUBE_REMOTE_COMPONENT_ID
    assert read_node.capability == YOUTUBE_VIDEO_METADATA_READ_CAPABILITY


def test_youtube_component_network_policy_and_capability_mode() -> None:
    component = phase41_runtime_registry().components[YOUTUBE_REMOTE_COMPONENT_ID]
    descriptor = component.capability(YOUTUBE_VIDEO_METADATA_READ_CAPABILITY)

    assert descriptor is not None
    assert descriptor.mode == CapabilityMode.READ.value
    assert component.network_policy == {
        "allowed_domains": ["oauth2.googleapis.com", "www.googleapis.com"],
        "required": True,
    }
    assert "*" not in component.network_policy["allowed_domains"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"video_id": ""},
        {"video_id": "bad id with spaces"},
        {"video_id": "https://www.youtube.com/watch?v=abc123DEF45"},
        {"url": "https://www.youtube.com/watch?v=abc123DEF45"},
        {"url": "https://attacker.example/watch?v=abc123DEF45"},
        {"url": "http://127.0.0.1:8000/metadata"},
        {"url": "http://169.254.169.254/latest/meta-data"},
        {"url": "file:///etc/passwd"},
        {"endpoint": "https://www.googleapis.com/youtube/v3/videos"},
        {"method": "GET"},
    ],
)
def test_youtube_input_rejects_invalid_ids_and_arbitrary_urls(payload: dict[str, object]) -> None:
    handler_registry = CapabilityHandlerRegistry()
    executor = PlaybookExecutor(handler_registry)
    register_youtube_runtime_handlers(
        handler_registry,
        youtube_service=YouTubeChannelService(transport=HttpYouTubeTransport(timeout=1)),
        access_tokens_by_install_id={"youtube-remote-test": "phase46-fixture-credential"},
    )

    with patch("channels.youtube.transport.urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
        outcome = executor.execute(
            plan=compile_youtube_plan(),
            trigger_event=youtube_event(payload),
        )

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = read_video_records(executor, outcome.execution.execution_id)[-1]
    assert failed.error_code in {"YOUTUBE_INPUT_INVALID", "INPUT_RESOLUTION_FAILED"}


def test_youtube_invalid_input_records_structured_failure() -> None:
    handler_registry = CapabilityHandlerRegistry()
    executor = PlaybookExecutor(handler_registry)
    register_youtube_runtime_handlers(
        handler_registry,
        youtube_service=YouTubeChannelService(transport=HttpYouTubeTransport(timeout=1)),
        access_tokens_by_install_id={"youtube-remote-test": "phase46-fixture-credential"},
    )

    outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event({"video_id": "bad id"}))

    failed = read_video_records(executor, outcome.execution.execution_id)[-1]
    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed.error_code == "YOUTUBE_INPUT_INVALID"


def test_youtube_authentication_missing_is_structured_failure() -> None:
    handler_registry = CapabilityHandlerRegistry()
    executor = PlaybookExecutor(handler_registry)
    register_youtube_runtime_handlers(
        handler_registry,
        youtube_service=YouTubeChannelService(transport=HttpYouTubeTransport(timeout=1)),
        access_tokens_by_install_id={},
    )

    outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

    failed = read_video_records(executor, outcome.execution.execution_id)[-1]
    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed.error_code == "YOUTUBE_AUTHENTICATION_REQUIRED"


class ErrorTransport(YouTubeTransport):
    def __init__(self, code: str, payload: dict[str, object] | None = None):
        self.code = code
        self.payload = payload or {}
        self.requests = 0

    def get_video(self, *, video_id: str, access_token: str):  # type: ignore[no-untyped-def]
        self.requests += 1
        if self.code == "not_found":
            from channels.youtube.transport import YouTubeResponse

            return YouTubeResponse(200, {"items": []}, {})
        if self.code == "malformed":
            from channels.youtube.transport import YouTubeResponse

            return YouTubeResponse(200, {"unexpected": []}, {})
        raise YouTubeChannelError(self.code, "Provider read failed.", self.payload)

    def create_upload_session(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("mutation forbidden")

    def upload_chunk(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("mutation forbidden")

    def query_upload_session(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("mutation forbidden")

    def exchange_code(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("oauth forbidden")

    def get_channel(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("unrelated read forbidden")

    def refresh_access_token(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("oauth forbidden")


@pytest.mark.parametrize(
    ("provider_code", "expected"),
    [
        ("youtube.network_error", "CAPABILITY_EXECUTION_FAILED"),
        ("youtube.rate_limited", "RATE_LIMITED"),
        ("youtube.authentication_required", "YOUTUBE_AUTHENTICATION_REQUIRED"),
        ("not_found", "YOUTUBE_VIDEO_NOT_FOUND"),
        ("malformed", "YOUTUBE_RESPONSE_MALFORMED"),
    ],
)
def test_youtube_provider_errors_are_structured(provider_code: str, expected: str) -> None:
    transport = ErrorTransport(provider_code, {"retry_after": 60})
    handler_registry = CapabilityHandlerRegistry()
    executor = PlaybookExecutor(handler_registry)
    register_youtube_runtime_handlers(
        handler_registry,
        youtube_service=YouTubeChannelService(transport=transport),
        access_tokens_by_install_id={"youtube-remote-test": "phase46-fixture-credential"},
    )

    outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

    failed = read_video_records(executor, outcome.execution.execution_id)[-1]
    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed.error_code == expected
    assert transport.requests == 1


def test_youtube_missing_handler_is_controlled_failure() -> None:
    executor = PlaybookExecutor(CapabilityHandlerRegistry())

    outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

    failed = read_video_records(executor, outcome.execution.execution_id)[-1]
    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed.error_code == "HANDLER_NOT_FOUND"


def test_youtube_no_core_provider_switch() -> None:
    source = inspect.getsource(PlaybookExecutor)

    assert "youtube" not in source.lower()
    assert "googleapis" not in source.lower()
