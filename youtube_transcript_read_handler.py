from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from channels.youtube.auth import YOUTUBE_READONLY_SCOPE, YOUTUBE_UPLOAD_SCOPE
from channels.youtube.errors import YouTubeChannelError
from channels.youtube.transport import YouTubeTransport
from src.core.runtime.events import utc_now_iso
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode

YOUTUBE_TRANSCRIPT_READ_CAPABILITY = "youtube.transcript.read"
YOUTUBE_OFFICIAL_CAPTIONS_COMPONENT_ID = "youtube-official-captions"
YOUTUBE_CAPTION_READ_SCOPES = (YOUTUBE_READONLY_SCOPE, YOUTUBE_UPLOAD_SCOPE)


@dataclass(frozen=True)
class CaptionTrack:
    caption_track_id: str
    language: str
    track_kind: str
    audio_track_type: str = ""
    last_updated: str = ""
    status: str = ""
    is_draft: bool = False
    raw: dict[str, Any] | None = None

    @classmethod
    def from_provider_item(cls, item: dict[str, Any]) -> "CaptionTrack":
        snippet = item.get("snippet") or {}
        return cls(
            caption_track_id=str(item.get("id") or ""),
            language=str(snippet.get("language") or ""),
            track_kind=str(snippet.get("trackKind") or ""),
            audio_track_type=str(snippet.get("audioTrackType") or ""),
            last_updated=str(snippet.get("lastUpdated") or ""),
            status=str(snippet.get("status") or ""),
            is_draft=bool(snippet.get("isDraft") or False),
            raw=dict(snippet),
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "audio_track_type": self.audio_track_type,
            "caption_track_id": self.caption_track_id,
            "is_draft": self.is_draft,
            "language": self.language,
            "last_updated": self.last_updated,
            "provider_track_identity": self.caption_track_id,
            "status": self.status,
            "track_kind": self.track_kind,
        }


def select_caption_track(
    tracks: list[CaptionTrack],
    *,
    preferred_languages: tuple[str, ...] = (),
    allow_asr: bool = False,
    preferred_audio_track: str = "",
) -> CaptionTrack:
    eligible = [
        track
        for track in tracks
        if track.caption_track_id
        and (not track.status or track.status == "serving")
        and not track.is_draft
        and (allow_asr or track.track_kind.lower() != "asr")
    ]
    if not eligible:
        raise PlaybookExecutionError("TRANSCRIPT_NOT_AVAILABLE", "No serving transcript track is available.")

    preferred = tuple(lang.lower() for lang in preferred_languages if lang)

    def rank(track: CaptionTrack) -> tuple[int, int, int, str, str]:
        language = track.language.lower()
        lang_rank = preferred.index(language) if language in preferred else len(preferred)
        audio_rank = 0 if preferred_audio_track and track.audio_track_type == preferred_audio_track else 1
        if not preferred_audio_track and track.audio_track_type in {"primary", ""}:
            audio_rank = 0
        kind_rank = 1 if track.track_kind.lower() == "asr" else 0
        return (lang_rank, audio_rank, kind_rank, language, track.caption_track_id)

    ranked = sorted(eligible, key=rank)
    best = ranked[0]
    best_rank = rank(best)[:3]
    tied = [track for track in ranked if rank(track)[:3] == best_rank]
    if len(tied) > 1:
        raise PlaybookExecutionError(
            "TRANSCRIPT_TRACK_AMBIGUOUS",
            "Multiple caption tracks match the configured transcript selection policy.",
            {"caption_track_ids": [track.caption_track_id for track in tied]},
        )
    return best


class YouTubeTranscriptReadHandler:
    component_id = YOUTUBE_OFFICIAL_CAPTIONS_COMPONENT_ID
    capability_id = YOUTUBE_TRANSCRIPT_READ_CAPABILITY

    def __init__(
        self,
        *,
        transport: YouTubeTransport,
        access_token_resolver: Callable[[str], str],
        scope_contract_resolver: Callable[[str], tuple[str, ...]] | None = None,
    ):
        self.transport = transport
        self.access_token_resolver = access_token_resolver
        self.scope_contract_resolver = scope_contract_resolver

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        _assert_no_secret_values(input_data, code=YOUTUBE_TRANSCRIPT_READ_CAPABILITY)
        video_id = str(input_data.get("video_id") or "").strip()
        if not video_id:
            raise PlaybookExecutionError("MISSING_REQUIRED_INPUT", "youtube.transcript.read requires video_id input.")
        install_id = resolved_node.install_id or (context.install_id if context else "install-yt-default")
        preferred_languages = tuple(str(item) for item in input_data.get("preferred_languages") or () if item)
        allow_asr = bool(input_data.get("allow_asr", False))
        preferred_audio_track = str(input_data.get("preferred_audio_track") or "")

        scopes = self.scope_contract_resolver(install_id) if self.scope_contract_resolver else ()
        if scopes and not any(scope in scopes for scope in YOUTUBE_CAPTION_READ_SCOPES):
            raise PlaybookExecutionError(
                "TRANSCRIPT_AUTH_REQUIRED",
                "YouTube caption retrieval requires a configured OAuth scope contract.",
                {"install_id": install_id},
            )
        if self.scope_contract_resolver is None:
            raise PlaybookExecutionError(
                "TRANSCRIPT_AUTH_REQUIRED",
                "YouTube caption retrieval is not configured with an OAuth scope contract.",
                {"install_id": install_id},
            )
        try:
            token = self.access_token_resolver(install_id)
        except Exception as exc:
            raise PlaybookExecutionError(
                "TRANSCRIPT_AUTH_REQUIRED",
                "YouTube caption retrieval requires an OAuth access token.",
                {"install_id": install_id},
            ) from exc
        if not token:
            raise PlaybookExecutionError(
                "TRANSCRIPT_AUTH_REQUIRED",
                "YouTube caption retrieval requires an OAuth access token.",
                {"install_id": install_id},
            )

        try:
            response = self.transport.list_captions(video_id=video_id, access_token=token)
        except YouTubeChannelError as exc:
            raise _caption_error(exc, video_id=video_id) from exc
        items = response.payload.get("items")
        if not isinstance(items, list):
            raise PlaybookExecutionError("TRANSCRIPT_DOWNLOAD_FAILED", "YouTube caption list response was malformed.")
        tracks = [CaptionTrack.from_provider_item(item) for item in items if isinstance(item, dict)]
        if not tracks:
            raise PlaybookExecutionError("TRANSCRIPT_NOT_AVAILABLE", "No YouTube caption tracks are available.")
        track = select_caption_track(
            tracks,
            preferred_languages=preferred_languages,
            allow_asr=allow_asr,
            preferred_audio_track=preferred_audio_track,
        )
        try:
            raw = self.transport.download_caption(caption_id=track.caption_track_id, access_token=token, tfmt="vtt")
        except YouTubeChannelError as exc:
            raise _caption_error(exc, video_id=video_id, caption_track_id=track.caption_track_id) from exc

        result = {
            "caption_track": track.metadata(),
            "content": raw.decode("utf-8"),
            "content_bytes": len(raw),
            "media_type": "text/vtt",
            "retrieved_at": utc_now_iso(),
            "source": "youtube_official_captions",
            "source_capability": YOUTUBE_TRANSCRIPT_READ_CAPABILITY,
            "video_id": video_id,
        }
        _assert_no_secret_values(result, code=YOUTUBE_TRANSCRIPT_READ_CAPABILITY)
        return result


def _caption_error(exc: YouTubeChannelError, *, video_id: str, caption_track_id: str = "") -> PlaybookExecutionError:
    code = getattr(exc, "code", "")
    metadata = {"video_id": video_id}
    if caption_track_id:
        metadata["caption_track_id"] = caption_track_id
    if code in {"youtube.authentication_required"}:
        return PlaybookExecutionError("TRANSCRIPT_AUTH_REQUIRED", "YouTube caption OAuth authentication is required.", metadata)
    if code in {"youtube.quota_or_forbidden"}:
        return PlaybookExecutionError("TRANSCRIPT_AUTH_FORBIDDEN", "YouTube caption retrieval was forbidden.", metadata)
    return PlaybookExecutionError("TRANSCRIPT_DOWNLOAD_FAILED", "YouTube caption retrieval failed.", metadata)
