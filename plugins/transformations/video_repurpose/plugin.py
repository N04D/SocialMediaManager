from __future__ import annotations

import hashlib
import json
import tempfile
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import channel_store
from media_store import list_media_assets, save_media_asset
from plugins.transformations.video_repurpose.ffmpeg_boundary import (
    FFmpegBoundaryError,
    ensure_managed_path,
    run_ffmpeg,
    run_ffprobe_json,
)
from src.core.content import AssetContract, ProvenanceRecord, TimelineSegment, TransformationContract
from src.core.media import MediaAsset, MediaInput, MediaSourceType, MediaStatus, MediaStoreOptions, media_type_for_mime

PLUGIN_ID = "plugin.video_repurpose"


@dataclass(frozen=True)
class RepurposeCandidate:
    candidate_id: str
    start_time: float
    end_time: float
    duration: float
    title: str
    transcript_excerpt: str
    score: float
    reason: str
    topic: str
    hook: str
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoMetadata:
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_present: bool

    @property
    def aspect_ratio(self) -> str:
        return f"{self.width}:{self.height}" if self.width and self.height else ""


@dataclass(frozen=True)
class RenderedShortResult:
    source_asset_id: str
    selected_candidate: RepurposeCandidate
    extract_run_id: str
    reframe_run_id: str
    caption_run_id: str
    extracted_asset: MediaAsset
    vertical_asset: MediaAsset
    captioned_asset: MediaAsset
    caption_segments: tuple[dict[str, Any], ...]
    reframe_strategy: str
    duplicate_reused: bool
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    variants: tuple[AssetContract, ...] = field(default_factory=tuple)


class VideoRepurposePlugin:
    capabilities = (
        "transformation.clip_candidates",
        "transformation.clip_selection",
        "transformation.video_extract",
        "transformation.video_reframe",
        "transformation.caption_render",
        "transformation.accepts.asset.video",
        "transformation.accepts.timeline.transcript",
        "transformation.accepts.canonical.text",
        "transformation.produces.transformation.clip_candidates",
        "transformation.produces.asset.short_video",
        "transformation.produces.asset.short_video.captioned",
        "transformation.produces.variant.social_text",
        "transformation.produces.variant.short_caption",
        "transformation.produces.variant.article",
        "asset.short_video",
        "asset.short_video.captioned",
        "variant.social_text",
        "variant.short_caption",
        "variant.article",
    )
    contract = TransformationContract(
        id="transformation.video_repurpose.v0",
        plugin_id=PLUGIN_ID,
        accepts=("asset.video", "timeline.transcript", "canonical.text"),
        produces=(
            "transformation.clip_candidates",
            "asset.short_video",
            "asset.short_video.captioned",
            "variant.social_text",
            "variant.short_caption",
            "variant.article",
        ),
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "plugin_id": PLUGIN_ID,
            "network_required": False,
            "shell": "not_used",
            "short_video_rendering": "available_with_local_ffmpeg",
            "render_steps": ["clip_selection", "video_extract", "video_reframe", "caption_render"],
        }

    def parse_timestamped_transcript(self, transcript: str) -> list[TimelineSegment]:
        segments: list[TimelineSegment] = []
        blocks = [block.strip() for block in transcript.strip().split("\n\n") if block.strip()]
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            timing = lines[0]
            if "-->" in timing:
                start_raw, end_raw = [part.strip() for part in timing.split("-->", maxsplit=1)]
                text = " ".join(lines[1:]).strip()
            else:
                match = lines[0].split(maxsplit=1)
                if len(match) != 2 or "-" not in match[0]:
                    raise ValueError("transcript.invalid_timing")
                start_raw, end_raw = [part.strip() for part in match[0].split("-", maxsplit=1)]
                text = match[1].strip()
            if not text:
                raise ValueError("transcript.segment_text_required")
            start = self._parse_time(start_raw)
            end = self._parse_time(end_raw)
            if end <= start:
                raise ValueError("transcript.invalid_segment_timing")
            segments.append(
                TimelineSegment(start_time=start, end_time=end, text=text, semantic_topic=self._topic(text))
            )
        if not segments:
            raise ValueError("transcript.required")
        return segments

    def clip_candidates(
        self,
        segments: list[TimelineSegment],
        *,
        max_candidates: int = 5,
        min_duration: float = 8.0,
        max_duration: float = 60.0,
    ) -> list[RepurposeCandidate]:
        candidates: list[RepurposeCandidate] = []
        for index, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            duration = round(float(segment.end_time) - float(segment.start_time), 3)
            if not text or duration <= 0 or duration < min_duration or duration > max_duration:
                continue
            starts_clean = text[:1].isupper() or text.lower().startswith(("what ", "why ", "when ", "how ", "a "))
            ends_clean = text.endswith((".", "?", "!"))
            if not starts_clean or not ends_clean:
                continue
            lowered = text.lower()
            hook_score = 0.22 if self._has_strong_opening(text) else 0.0
            question_score = 0.14 if "?" in text else 0.0
            statement_score = 0.14 if any(word in lowered for word in ["means", "is", "are", "why"]) else 0.0
            story_score = 0.12 if any(word in lowered for word in ["when", "you", "daily", "simple"]) else 0.0
            duration_score = max(0.0, 1.0 - abs(duration - 28.0) / 40.0)
            completeness_score = min(len(text.split()) / 24.0, 1.0) * 0.24
            score = round(
                duration_score * 0.28
                + completeness_score
                + hook_score
                + question_score
                + statement_score
                + story_score,
                4,
            )
            topic = segment.semantic_topic or self._topic(text)
            candidates.append(
                RepurposeCandidate(
                    candidate_id=f"clip-candidate-{index}",
                    start_time=float(segment.start_time),
                    end_time=float(segment.end_time),
                    duration=duration,
                    title=self._title(text),
                    transcript_excerpt=text[:320],
                    score=score,
                    reason="Strong standalone opening; complete thought; duration within configured range",
                    topic=topic,
                    hook=self._hook(text),
                    provenance={
                        "plugin_id": PLUGIN_ID,
                        "strategy": "deterministic_v1",
                        "min_duration": min_duration,
                        "max_duration": max_duration,
                    },
                )
            )
        return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.start_time))[:max_candidates]

    def import_long_form_video(
        self,
        *,
        app_runtime,
        workspace_id: str,
        local_path: Path,
        created_by: str = "",
        source_reference: str = "",
    ) -> MediaAsset:
        source_path = local_path.expanduser().resolve()
        if source_path.suffix.lower() != ".mp4":
            raise ValueError("video_import.unsupported_format")
        metadata = self.probe_video(source_path)
        provider = app_runtime.media_provider()
        stored = provider.store(
            MediaInput(
                local_path=source_path,
                original_filename=source_path.name,
                declared_mime_type="video/mp4",
                source_type=MediaSourceType.LOCAL_IMPORT.value,
                source_reference=source_reference or str(source_path.name),
            ),
            MediaStoreOptions(
                workspace_id=workspace_id,
                purpose="media.video_import",
                maximum_size=250_000_000,
                allowed_mime_types=("video/mp4",),
                metadata={"plugin_id": PLUGIN_ID},
            ),
        )
        now = channel_store.now_iso()
        asset = MediaAsset(
            id=f"media_{uuid4().hex}",
            workspace_id=workspace_id,
            media_type=media_type_for_mime(stored.mime_type),
            mime_type=stored.mime_type,
            original_filename=source_path.name,
            display_name=source_path.name,
            storage_provider_id=stored.provider_id,
            storage_reference=stored.storage_reference,
            checksum_algorithm="sha256",
            checksum=stored.checksum,
            file_size=stored.file_size,
            width=metadata.width,
            height=metadata.height,
            duration_ms=int(metadata.duration * 1000),
            status=MediaStatus.AVAILABLE.value,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            source_type=MediaSourceType.LOCAL_IMPORT.value,
            source_reference=source_reference or source_path.name,
            metadata={
                "video_metadata": asdict(metadata),
                "provenance": {"plugin_id": PLUGIN_ID, "import_method": "local_video_import"},
                "provider_metadata": stored.provider_metadata,
            },
        )
        return save_media_asset(asset)

    def render_selected_clip(
        self,
        *,
        app_runtime,
        content_service,
        workspace_id: str,
        source_asset_id: str,
        selected: RepurposeCandidate,
        transcript_segments: list[TimelineSegment],
        target_width: int = 1080,
        target_height: int = 1920,
        test_mode: bool = False,
        actor: str = "",
    ) -> RenderedShortResult:
        target_width = 360 if test_mode else target_width
        target_height = 640 if test_mode else target_height
        render_config = {
            "target_width": target_width,
            "target_height": target_height,
            "caption_style": "phase36_v1",
            "selected_candidate_id": selected.candidate_id,
        }
        duplicate_key = self._duplicate_key(source_asset_id, selected, render_config)
        existing = self._existing_short(workspace_id, duplicate_key)
        if existing is not None:
            return RenderedShortResult(
                source_asset_id=source_asset_id,
                selected_candidate=selected,
                extract_run_id=str(existing.metadata.get("extract_run_id", "")),
                reframe_run_id=str(existing.metadata.get("reframe_run_id", "")),
                caption_run_id=str(existing.metadata.get("caption_run_id", "")),
                extracted_asset=existing,
                vertical_asset=existing,
                captioned_asset=existing,
                caption_segments=tuple(existing.metadata.get("caption_segments") or ()),
                reframe_strategy=str(existing.metadata.get("reframe_strategy", "")),
                duplicate_reused=True,
                status="succeeded",
                evidence={"duplicate_key": duplicate_key, "reused_asset_id": existing.id},
                variants=self.derived_variants(selected=selected, title="Rendered short"),
            )
        graph = content_service.graph_service
        extract_run = graph.record_transformation_run(
            workspace_id=workspace_id,
            transformation=TransformationContract(
                id="transformation.video_extract.phase36",
                plugin_id=PLUGIN_ID,
                accepts=("asset.video", "transformation.clip_candidates"),
                produces=("asset.video.extracted",),
            ),
            input_refs=(source_asset_id, selected.candidate_id),
            configuration={"start_time": selected.start_time, "end_time": selected.end_time},
            evidence={"status": "running"},
        )
        with tempfile.TemporaryDirectory(prefix="phase36-video-") as tmp:
            tmp_root = Path(tmp)
            source_path = self._materialize_asset_to_path(app_runtime, source_asset_id, workspace_id, tmp_root)
            extracted_path = tmp_root / "extracted.mp4"
            try:
                self.extract_video_segment(
                    source_path=source_path,
                    output_path=extracted_path,
                    start_time=selected.start_time,
                    duration=selected.duration,
                    managed_root=tmp_root,
                )
                extracted_meta = self.probe_video(extracted_path)
                extracted_asset = self._store_rendered_asset(
                    app_runtime=app_runtime,
                    workspace_id=workspace_id,
                    path=extracted_path,
                    filename=f"{selected.candidate_id}-extracted.mp4",
                    created_by=actor,
                    metadata={
                        "asset_type": "extracted_video",
                        "source_asset_id": source_asset_id,
                        "transformation_run_id": extract_run.id,
                        "selected_candidate": asdict(selected),
                        "video_metadata": asdict(extracted_meta),
                    },
                )
                source_meta = self.probe_video(source_path)
                strategy = self.reframe_strategy(source_meta)
                reframe_run = graph.record_transformation_run(
                    workspace_id=workspace_id,
                    transformation=TransformationContract(
                        id="transformation.video_reframe.phase36",
                        plugin_id=PLUGIN_ID,
                        accepts=("asset.video.extracted",),
                        produces=("asset.short_video",),
                    ),
                    input_refs=(extracted_asset.id,),
                    configuration={"strategy": strategy, **render_config},
                    evidence={"status": "running"},
                )
                vertical_path = tmp_root / "vertical.mp4"
                self.reframe_video(
                    source_path=extracted_path,
                    output_path=vertical_path,
                    target_width=target_width,
                    target_height=target_height,
                    strategy=strategy,
                    managed_root=tmp_root,
                )
                vertical_meta = self.probe_video(vertical_path)
                vertical_asset = self._store_rendered_asset(
                    app_runtime=app_runtime,
                    workspace_id=workspace_id,
                    path=vertical_path,
                    filename=f"{selected.candidate_id}-vertical.mp4",
                    created_by=actor,
                    metadata={
                        "asset_type": "short_video",
                        "source_asset_id": source_asset_id,
                        "transformation_run_id": reframe_run.id,
                        "extract_run_id": extract_run.id,
                        "reframe_strategy": strategy,
                        "video_metadata": asdict(vertical_meta),
                    },
                )
                caption_segments = self.caption_subset(transcript_segments, selected)
                caption_run = graph.record_transformation_run(
                    workspace_id=workspace_id,
                    transformation=TransformationContract(
                        id="transformation.caption_render.phase36",
                        plugin_id=PLUGIN_ID,
                        accepts=("asset.short_video", "timeline.transcript"),
                        produces=("asset.short_video.captioned",),
                    ),
                    input_refs=(vertical_asset.id, selected.candidate_id),
                    configuration={"caption_style": "phase36_v1", **render_config},
                    evidence={"status": "running", "caption_count": len(caption_segments)},
                )
                captioned_path = tmp_root / "captioned.mp4"
                self.render_captions(
                    source_path=vertical_path,
                    output_path=captioned_path,
                    caption_segments=caption_segments,
                    target_width=target_width,
                    target_height=target_height,
                    managed_root=tmp_root,
                )
                captioned_meta = self.probe_video(captioned_path)
                if not self.integrity_ok(captioned_path, expected_width=target_width, expected_height=target_height):
                    raise FFmpegBoundaryError("video_integrity.failed")
                captioned_asset = self._store_rendered_asset(
                    app_runtime=app_runtime,
                    workspace_id=workspace_id,
                    path=captioned_path,
                    filename=f"{selected.candidate_id}-captioned-short.mp4",
                    created_by=actor,
                    metadata={
                        "asset_type": "short_video",
                        "source_asset_id": source_asset_id,
                        "transformation_run_ids": [extract_run.id, reframe_run.id, caption_run.id],
                        "extract_run_id": extract_run.id,
                        "reframe_run_id": reframe_run.id,
                        "caption_run_id": caption_run.id,
                        "selected_candidate": asdict(selected),
                        "caption_segments": caption_segments,
                        "original_timestamps": {"start": selected.start_time, "end": selected.end_time},
                        "reframe_strategy": strategy,
                        "render_config": render_config,
                        "duplicate_key": duplicate_key,
                        "video_metadata": asdict(captioned_meta),
                        "preview_ready": True,
                        "captions_included": True,
                    },
                )
            except Exception as exc:
                graph.record_transformation_run(
                    workspace_id=workspace_id,
                    transformation=TransformationContract(
                        id="transformation.video_repurpose.failure.phase36",
                        plugin_id=PLUGIN_ID,
                        accepts=("asset.video",),
                        produces=(),
                    ),
                    input_refs=(source_asset_id, selected.candidate_id),
                    configuration=render_config,
                    evidence={"status": "failed", "error": str(exc)[:500]},
                )
                raise
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=f"asset.{source_asset_id}",
            relationship_type="transformed_by",
            to_entity_id=selected.candidate_id,
            metadata={"step": "clip_candidate_detection"},
            provenance={"actor_type": "plugin", "plugin_id": PLUGIN_ID},
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=selected.candidate_id,
            relationship_type="selected_as",
            to_entity_id=extracted_asset.id,
            metadata={"start": selected.start_time, "end": selected.end_time, "extract_run_id": extract_run.id},
            provenance={"actor_type": "user" if actor else "plugin", "plugin_id": PLUGIN_ID},
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=extracted_asset.id,
            relationship_type="transformed_by",
            to_entity_id=vertical_asset.id,
            metadata={"reframe_run_id": reframe_run.id, "strategy": strategy},
            provenance={"actor_type": "plugin", "plugin_id": PLUGIN_ID},
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=vertical_asset.id,
            relationship_type="transformed_by",
            to_entity_id=captioned_asset.id,
            metadata={"caption_run_id": caption_run.id},
            provenance={"actor_type": "plugin", "plugin_id": PLUGIN_ID},
        )
        variants = self.derived_variants(selected=selected, title="Rendered short")
        return RenderedShortResult(
            source_asset_id=source_asset_id,
            selected_candidate=selected,
            extract_run_id=extract_run.id,
            reframe_run_id=reframe_run.id,
            caption_run_id=caption_run.id,
            extracted_asset=extracted_asset,
            vertical_asset=vertical_asset,
            captioned_asset=captioned_asset,
            caption_segments=tuple(caption_segments),
            reframe_strategy=strategy,
            duplicate_reused=False,
            status="succeeded",
            evidence={"duplicate_key": duplicate_key, "captioned_asset_id": captioned_asset.id},
            variants=variants,
        )

    def probe_video(self, path: Path) -> VideoMetadata:
        payload = run_ffprobe_json(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,r_frame_rate,duration",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
        streams = payload.get("streams") or []
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio_present = any(stream.get("codec_type") == "audio" for stream in streams)
        fps = self._fps(str(video.get("r_frame_rate") or "0/1"))
        duration = float(video.get("duration") or (payload.get("format") or {}).get("duration") or 0)
        return VideoMetadata(
            duration=round(duration, 3),
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            fps=fps,
            codec=str(video.get("codec_name") or ""),
            audio_present=audio_present,
        )

    def extract_video_segment(
        self,
        *,
        source_path: Path,
        output_path: Path,
        start_time: float,
        duration: float,
        managed_root: Path,
    ) -> None:
        source = ensure_managed_path(source_path, root=managed_root)
        output = ensure_managed_path(output_path, root=managed_root)
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start_time:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

    def reframe_video(
        self,
        *,
        source_path: Path,
        output_path: Path,
        target_width: int,
        target_height: int,
        strategy: str,
        managed_root: Path,
    ) -> None:
        source = ensure_managed_path(source_path, root=managed_root)
        output = ensure_managed_path(output_path, root=managed_root)
        if strategy == "center_crop":
            vf = (
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
                f"crop={target_width}:{target_height}"
            )
        elif strategy == "portrait_passthrough":
            vf = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
        else:
            vf = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

    def render_captions(
        self,
        *,
        source_path: Path,
        output_path: Path,
        caption_segments: list[dict[str, Any]],
        target_width: int,
        target_height: int,
        managed_root: Path,
    ) -> None:
        source = ensure_managed_path(source_path, root=managed_root)
        output = ensure_managed_path(output_path, root=managed_root)
        srt_path = managed_root / "captions.srt"
        srt_path.write_text(self._srt(caption_segments), encoding="utf-8")
        font_size = max(18, int(target_height * 0.038))
        margin_v = max(36, int(target_height * 0.08))
        subtitles = str(srt_path).replace("\\", "\\\\").replace(":", "\\:")
        vf = (
            f"subtitles='{subtitles}':force_style="
            f"'FontName=DejaVu Sans,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H90000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV={margin_v}'"
        )
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

    def caption_subset(self, segments: list[TimelineSegment], selected: RepurposeCandidate) -> list[dict[str, Any]]:
        subset: list[dict[str, Any]] = []
        for segment in segments:
            overlap_start = max(float(segment.start_time), selected.start_time)
            overlap_end = min(float(segment.end_time), selected.end_time)
            if overlap_end <= overlap_start:
                continue
            local_start = round(overlap_start - selected.start_time, 3)
            local_end = round(overlap_end - selected.start_time, 3)
            subset.append(
                {
                    "start": local_start,
                    "end": local_end,
                    "text": self._wrap_caption(segment.text),
                    "original_start": float(segment.start_time),
                    "original_end": float(segment.end_time),
                }
            )
        return subset

    def integrity_ok(self, path: Path, *, expected_width: int, expected_height: int) -> bool:
        if not path.exists() or path.stat().st_size <= 0:
            return False
        metadata = self.probe_video(path)
        return (
            metadata.duration > 0
            and metadata.width == expected_width
            and metadata.height == expected_height
            and metadata.codec != ""
        )

    def short_video_asset_contract(
        self,
        *,
        selected: RepurposeCandidate,
        source_asset_id: str = "",
        synthetic_video_available: bool = False,
    ) -> dict[str, Any]:
        status = "available" if synthetic_video_available and source_asset_id else "rendering capability not configured"
        asset_id = f"short-video-{selected.candidate_id}"
        return {
            "asset_id": asset_id,
            "asset_type": "short_video",
            "status": status,
            "source_asset_id": source_asset_id,
            "start": selected.start_time,
            "end": selected.end_time,
            "duration": selected.duration,
            "format": "mp4",
            "aspect_ratio": "9:16",
            "provenance": {"plugin_id": PLUGIN_ID, "candidate_id": selected.candidate_id},
        }

    def social_text_variant(self, *, selected: RepurposeCandidate, title: str = "") -> AssetContract:
        text = (
            f"{selected.hook}\n\n{selected.transcript_excerpt}\n\nA short reflection from the source material."
        ).strip()
        return AssetContract(
            asset_id=f"variant-social-{selected.candidate_id}",
            asset_type="variant.social_text",
            text=text,
            metadata={"title": title, "candidate_id": selected.candidate_id, "topic": selected.topic},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def article_variant(self, *, selected: RepurposeCandidate, title: str = "") -> AssetContract:
        text = (
            f"# {title or selected.topic.title()}\n\n"
            f"{selected.transcript_excerpt}\n\n"
            "This article variant expands the selected segment into a concise website draft."
        ).strip()
        return AssetContract(
            asset_id=f"variant-article-{selected.candidate_id}",
            asset_type="variant.article",
            text=text,
            metadata={"title": title, "candidate_id": selected.candidate_id, "topic": selected.topic},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def short_caption_variant(self, *, selected: RepurposeCandidate, title: str = "") -> AssetContract:
        text = f"{selected.hook}\n\n{selected.topic.title()}: {selected.transcript_excerpt[:140]}".strip()
        return AssetContract(
            asset_id=f"variant-short-caption-{selected.candidate_id}",
            asset_type="variant.short_caption",
            text=text,
            metadata={"title": title, "candidate_id": selected.candidate_id, "topic": selected.topic},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def commercial_cta_variant(self, *, selected: RepurposeCandidate, product_title: str) -> AssetContract:
        return AssetContract(
            asset_id=f"variant-cta-{selected.candidate_id}",
            asset_type="variant.commercial_cta",
            text=f"Explore the related {product_title} design.",
            metadata={"candidate_id": selected.candidate_id, "product_title": product_title, "no_discount_claim": True},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def derived_variants(self, *, selected: RepurposeCandidate, title: str = "") -> tuple[AssetContract, ...]:
        return (
            self.social_text_variant(selected=selected, title=title),
            self.short_caption_variant(selected=selected, title=title),
            self.article_variant(selected=selected, title=title),
        )

    def reframe_strategy(self, metadata: VideoMetadata) -> str:
        if metadata.height > metadata.width:
            return "portrait_passthrough"
        if metadata.width >= metadata.height:
            return "center_crop"
        return "fit"

    def _materialize_asset_to_path(self, app_runtime, asset_id: str, workspace_id: str, tmp_root: Path) -> Path:
        asset = app_runtime.media_runtime(None).get_asset(asset_id, workspace_id=workspace_id)
        provider = app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        target = tmp_root / (asset.original_filename or f"{asset.id}.mp4")
        with target.open("wb") as handle:
            for chunk in provider.open_stream(asset.storage_reference):
                handle.write(chunk)
        return target

    def _store_rendered_asset(
        self,
        *,
        app_runtime,
        workspace_id: str,
        path: Path,
        filename: str,
        created_by: str,
        metadata: dict[str, Any],
    ) -> MediaAsset:
        video_metadata = metadata.get("video_metadata") or asdict(self.probe_video(path))
        provider = app_runtime.media_provider()
        stored = provider.store(
            MediaInput(
                local_path=path,
                original_filename=filename,
                declared_mime_type="video/mp4",
                source_type=MediaSourceType.GENERATED.value,
                source_reference=metadata.get("source_asset_id", ""),
            ),
            MediaStoreOptions(
                workspace_id=workspace_id,
                purpose="media.video_render",
                maximum_size=250_000_000,
                allowed_mime_types=("video/mp4",),
                metadata={"plugin_id": PLUGIN_ID},
            ),
        )
        now = channel_store.now_iso()
        asset = MediaAsset(
            id=f"media_{uuid4().hex}",
            workspace_id=workspace_id,
            media_type=media_type_for_mime(stored.mime_type),
            mime_type=stored.mime_type,
            original_filename=filename,
            display_name=filename,
            storage_provider_id=stored.provider_id,
            storage_reference=stored.storage_reference,
            checksum_algorithm="sha256",
            checksum=stored.checksum,
            file_size=stored.file_size,
            width=int(video_metadata.get("width") or 0),
            height=int(video_metadata.get("height") or 0),
            duration_ms=int(float(video_metadata.get("duration") or 0) * 1000),
            status=MediaStatus.AVAILABLE.value,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            source_type=MediaSourceType.GENERATED.value,
            source_reference=str(metadata.get("source_asset_id") or ""),
            metadata=dict(metadata) | {"provider_metadata": stored.provider_metadata},
        )
        return save_media_asset(asset)

    @staticmethod
    def _existing_short(workspace_id: str, duplicate_key: str) -> MediaAsset | None:
        return next(
            (
                asset
                for asset in list_media_assets(workspace_id=workspace_id)
                if asset.metadata.get("duplicate_key") == duplicate_key
                and asset.status == MediaStatus.AVAILABLE.value
                and asset.metadata.get("asset_type") == "short_video"
            ),
            None,
        )

    @staticmethod
    def _duplicate_key(source_asset_id: str, selected: RepurposeCandidate, render_config: dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "source_asset_id": source_asset_id,
                "start": selected.start_time,
                "end": selected.end_time,
                "render_config": render_config,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _has_strong_opening(text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith(("when ", "why ", "what ", "a simple", "the strongest"))

    @staticmethod
    def _parse_time(value: str) -> float:
        normalized = value.replace(",", ".")
        parts = normalized.split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        raise ValueError("time.invalid")

    @staticmethod
    def _fps(value: str) -> float:
        if "/" not in value:
            return float(value or 0)
        numerator, denominator = value.split("/", maxsplit=1)
        denominator_value = float(denominator or 1)
        return round(float(numerator or 0) / denominator_value, 3) if denominator_value else 0.0

    @staticmethod
    def _title(text: str) -> str:
        hook = VideoRepurposePlugin._hook(text)
        return hook[:80]

    @staticmethod
    def _topic(text: str) -> str:
        lowered = text.lower()
        for keyword in ["sabr", "patience", "reflection", "daily life", "endurance"]:
            if keyword in lowered:
                return keyword
        return "source segment"

    @staticmethod
    def _hook(text: str) -> str:
        first = text.split(".", maxsplit=1)[0].strip()
        return first if first else "A useful idea from the source"

    @staticmethod
    def _wrap_caption(text: str) -> str:
        return "\n".join(textwrap.wrap(text.strip(), width=34, max_lines=2, placeholder="..."))

    @staticmethod
    def _srt(segments: list[dict[str, Any]]) -> str:
        blocks = []
        for index, segment in enumerate(segments, start=1):
            blocks.append(
                f"{index}\n"
                f"{VideoRepurposePlugin._srt_time(float(segment['start']))} --> "
                f"{VideoRepurposePlugin._srt_time(float(segment['end']))}\n"
                f"{segment['text']}\n"
            )
        return "\n".join(blocks)

    @staticmethod
    def _srt_time(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, remainder = divmod(millis, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, ms = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
