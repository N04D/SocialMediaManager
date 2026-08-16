from __future__ import annotations

import pytest

from channels.youtube.errors import YouTubeChannelError
from channels.youtube.transport import FakeYouTubeTransport
from src.core.runtime.events import EventEnvelope
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from youtube_transcript_read_handler import YouTubeTranscriptReadHandler, select_caption_track, CaptionTrack


def _track(track_id: str, *, language: str = "en", kind: str = "standard", status: str = "serving", draft: bool = False):
    return {
        "id": track_id,
        "snippet": {
            "audioTrackType": "primary",
            "isDraft": draft,
            "language": language,
            "lastUpdated": "2026-08-10T00:00:00Z",
            "status": status,
            "trackKind": kind,
        },
    }


def _ctx():
    event = EventEnvelope(
        event_id="evt",
        event_type="youtube.video.published",
        source="youtube-data-api-uploads",
        payload={"video_id": "vid"},
    )
    return ExecutionContext(execution_id="exec", deployment_id="dep", trigger_event=event)


def test_track_selection_prefers_language_standard_ignores_draft_and_non_serving():
    tracks = [
        CaptionTrack.from_provider_item(_track("draft", draft=True)),
        CaptionTrack.from_provider_item(_track("syncing", status="syncing")),
        CaptionTrack.from_provider_item(_track("asr-en", kind="ASR")),
        CaptionTrack.from_provider_item(_track("nl", language="nl")),
        CaptionTrack.from_provider_item(_track("en", language="en")),
    ]
    selected = select_caption_track(tracks, preferred_languages=("en",), allow_asr=True)
    assert selected.caption_track_id == "en"


def test_track_selection_asr_is_explicit_and_ambiguity_blocks():
    asr = select_caption_track(
        [CaptionTrack.from_provider_item(_track("asr-en", kind="ASR"))],
        preferred_languages=("en",),
        allow_asr=True,
    )
    assert asr.track_kind == "ASR"

    with pytest.raises(Exception) as err:
        select_caption_track(
            [CaptionTrack.from_provider_item(_track("a")), CaptionTrack.from_provider_item(_track("b"))],
            preferred_languages=("en",),
        )
    assert err.value.code == "TRANSCRIPT_TRACK_AMBIGUOUS"


def test_official_caption_reader_lists_downloads_once_and_uses_no_mutations():
    transport = FakeYouTubeTransport()
    transport.captions_by_video_id["vid"] = [_track("cap-1", language="en")]
    transport.caption_downloads["cap-1"] = b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n"
    handler = YouTubeTranscriptReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "tok",
        scope_contract_resolver=lambda _: ("https://www.googleapis.com/auth/youtube.readonly",),
    )
    result = handler.execute(
        context=_ctx(),
        node=PlaybookNode(node_id="n", kind="capability", config={}),
        resolved_node=ExecutionPlanNode(node_id="n", kind="capability", install_id="install"),
        input_data={"video_id": "vid", "preferred_languages": ["en"]},
    )

    assert result["caption_track"]["caption_track_id"] == "cap-1"
    assert result["media_type"] == "text/vtt"
    endpoints = [request["endpoint"] for request in transport.requests]
    assert endpoints == ["captions.list", "captions.download"]
    assert "captions.insert" not in endpoints
    assert "captions.update" not in endpoints
    assert "captions.delete" not in endpoints


def test_official_caption_reader_auth_forbidden_and_no_captions_are_structured():
    transport = FakeYouTubeTransport()
    handler = YouTubeTranscriptReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "",
        scope_contract_resolver=lambda _: ("https://www.googleapis.com/auth/youtube.readonly",),
    )
    with pytest.raises(Exception) as auth:
        handler.execute(
            context=_ctx(),
            node=PlaybookNode(node_id="n", kind="capability", config={}),
            resolved_node=ExecutionPlanNode(node_id="n", kind="capability", install_id="install"),
            input_data={"video_id": "vid"},
        )
    assert auth.value.code == "TRANSCRIPT_AUTH_REQUIRED"

    transport.error_override = YouTubeChannelError("youtube.quota_or_forbidden", "forbidden")
    handler = YouTubeTranscriptReadHandler(
        transport=transport,
        access_token_resolver=lambda _: "tok",
        scope_contract_resolver=lambda _: ("https://www.googleapis.com/auth/youtube.readonly",),
    )
    with pytest.raises(Exception) as forbidden:
        handler.execute(
            context=_ctx(),
            node=PlaybookNode(node_id="n", kind="capability", config={}),
            resolved_node=ExecutionPlanNode(node_id="n", kind="capability", install_id="install"),
            input_data={"video_id": "vid"},
        )
    assert forbidden.value.code == "TRANSCRIPT_AUTH_FORBIDDEN"
