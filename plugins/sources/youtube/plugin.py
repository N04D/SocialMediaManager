from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qs, urlparse

import channel_store
from src.core.content import Entity, TimelineSegment

PLUGIN_ID = "source.youtube"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


class YouTubeSourceError(ValueError):
    pass


class YouTubeSourcePlugin:
    capabilities = (
        "source.video",
        "source.youtube",
        "source.transcript",
        "source.transcript.import",
        "source.metadata",
        "timeline.transcript",
        "asset.video",
        "asset.transcript",
        "asset.transcript.timeline",
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "plugin_id": PLUGIN_ID,
            "transcript_retrieval": "not_configured",
            "message": "Transcript retrieval not configured",
            "fallbacks": ["Paste transcript", "Import transcript"],
            "network_required": False,
        }

    def validate_video_ref(self, *, url: str = "", video_id: str = "") -> dict[str, str]:
        resolved_id = (video_id or "").strip()
        resolved_url = (url or "").strip()
        if resolved_url:
            parsed = urlparse(resolved_url)
            host = parsed.netloc.lower()
            if host in {"youtu.be", "www.youtu.be"}:
                resolved_id = parsed.path.strip("/")
            elif host.endswith("youtube.com"):
                resolved_id = parse_qs(parsed.query).get("v", [resolved_id])[0]
            else:
                raise YouTubeSourceError("youtube_source.invalid_host")
        if not VIDEO_ID_RE.match(resolved_id):
            raise YouTubeSourceError("youtube_source.invalid_video_id")
        if not resolved_url:
            resolved_url = f"https://www.youtube.com/watch?v={resolved_id}"
        return {"video_id": resolved_id, "url": resolved_url}

    def parse_timestamped_transcript(self, transcript: str) -> list[TimelineSegment]:
        segments: list[TimelineSegment] = []
        for raw_line in transcript.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^(?P<start>[0-9:.]+)\s*[-–]\s*(?P<end>[0-9:.]+)\s+(?P<text>.+)$", line)
            if match is None:
                start = segments[-1].end_time if segments else 0.0
                end = start + 30.0
                text = line
            else:
                start = self._parse_time(match.group("start"))
                end = self._parse_time(match.group("end"))
                text = match.group("text").strip()
            if end <= start:
                raise YouTubeSourceError("youtube_source.invalid_segment_timing")
            segments.append(TimelineSegment(start_time=start, end_time=end, text=text))
        if not segments:
            raise YouTubeSourceError("youtube_source.transcript_required")
        return segments

    def import_source(
        self,
        *,
        content_service,
        workspace_id: str,
        url: str = "",
        video_id: str = "",
        title: str,
        transcript: str,
        edited_transcript: str = "",
        channel_name: str = "",
        duration: float = 0,
        language: str = "",
        actor: str = "",
    ) -> dict[str, Any]:
        resolved = self.validate_video_ref(url=url, video_id=video_id)
        segments = self.parse_timestamped_transcript(transcript)
        canonical_text = (edited_transcript or self._plain_transcript(segments)).strip()
        now = channel_store.now_iso()
        entity = Entity(
            id=f"entity.youtube.video.{resolved['video_id']}",
            entity_type="video",
            source_plugin=PLUGIN_ID,
            external_ref=resolved["video_id"],
            title=title.strip() or resolved["video_id"],
            metadata={
                "url": resolved["url"],
                "channel_name": channel_name,
                "duration": duration,
                "language": language,
            },
            created_at=now,
            updated_at=now,
        )
        content_service.graph_service.save_entity(entity)
        item = content_service.create_youtube_source_content(
            workspace_id=workspace_id,
            youtube_url=resolved["url"],
            video_id=resolved["video_id"],
            title=title,
            transcript=self._plain_transcript(segments),
            edited_transcript=canonical_text,
            transcript_provenance={
                "provider": PLUGIN_ID,
                "plugin_id": PLUGIN_ID,
                "actor_type": "plugin",
                "actor_id": actor,
                "import_method": "paste_transcript",
                "timeline_segments_json": self._timeline_json(segments),
            },
            created_by=actor,
            metadata={
                "source_plugin": PLUGIN_ID,
                "timeline_segments_json": self._timeline_json(segments),
                "transcript_retrieval": "not_configured",
            },
        )
        item.primary_source_entity_id = entity.id
        item.primary_source_metadata.update(entity.metadata)
        item.canonical_metadata.update(
            {
                "timeline_segments_json": self._timeline_json(segments),
                "channel_name": channel_name,
                "duration": duration,
                "language": language,
            }
        )
        content_service.content_repository.save(item)
        return {
            "entity": entity,
            "content_item": item,
            "source": {
                "source_type": "youtube_video",
                "entity_id": entity.id,
                "source_plugin": PLUGIN_ID,
                "ref": resolved["url"],
                "metadata": dict(item.primary_source_metadata),
            },
            "canonical": {
                "text": canonical_text,
                "timeline": segments,
                "metadata": dict(item.canonical_metadata),
                "provenance": dict(item.source_provenance),
            },
            "transcript_retrieval": "not_configured",
        }

    @staticmethod
    def _parse_time(value: str) -> float:
        parts = [float(part) for part in value.split(":")]
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        raise YouTubeSourceError("youtube_source.invalid_time")

    @staticmethod
    def _plain_transcript(segments: list[TimelineSegment]) -> str:
        return "\n".join(segment.text for segment in segments)

    @staticmethod
    def _timeline_json(segments: list[TimelineSegment]) -> str:
        import json

        return json.dumps([asdict(segment) for segment in segments], ensure_ascii=True, sort_keys=True)
