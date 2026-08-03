from __future__ import annotations

from pathlib import Path
from typing import Any

from media_store import save_media_asset
from plugins.providers.local_transcription import (
    DeterministicTranscriptionEngine,
    LocalTranscriptionConfig,
    LocalTranscriptionProvider,
    TranscriptSegment,
)
from plugins.transformations.video_repurpose.ffmpeg_boundary import run_ffmpeg
from src.core.plugins.manifest import PluginStatus
from tests.phase36_support import Phase36Harness


class Phase37Harness(Phase36Harness):
    def __init__(
        self, *, with_audio: bool = True, invalid_segments: tuple[TranscriptSegment, ...] | None = None
    ) -> None:
        super().__init__()
        if not with_audio:
            self.video_path = self.root / "fixtures" / "phase37-no-audio.mp4"
            self.create_no_audio_video(self.video_path, width=640, height=360, duration=20)
            self.video_asset = self.plugin.import_long_form_video(
                app_runtime=self.runtime,
                workspace_id="creator-video",
                local_path=self.video_path,
                created_by="phase37-test",
                source_reference="synthetic_phase37_no_audio",
            )
            self.video_asset.metadata["audio_present"] = False
            save_media_asset(self.video_asset)
        engine = (
            DeterministicTranscriptionEngine(segments=invalid_segments)
            if invalid_segments
            else DeterministicTranscriptionEngine()
        )
        self.transcription_provider = LocalTranscriptionProvider(
            provider_config=LocalTranscriptionConfig(
                engine="deterministic_fixture",
                model="deterministic-fixture",
                language="auto",
            ),
            engine=engine,
        )
        runtime_record = self.runtime.runtimes["provider.transcription.local"]
        runtime_record.instance = self.transcription_provider
        runtime_record.services["transcription_provider"] = self.transcription_provider
        runtime_record.health = self.transcription_provider.health_check()
        runtime_record.status = PluginStatus.READY

    @staticmethod
    def create_no_audio_video(path: Path, *, width: int, height: int, duration: int) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size={width}x{height}:rate=24:duration={duration}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-an",
                str(path),
            ],
            timeout=60,
        )

    def transcribe(self, *, force_new: bool = False, language: str = "auto") -> Any:
        return self.transcription_provider.transcribe(
            app_runtime=self.runtime,
            content_service=self.content,
            workspace_id="creator-video",
            source_asset_id=self.video_asset.id,
            language=language,
            force_new=force_new,
            actor="phase37-test",
        )

    def transcribe_and_render(self) -> dict[str, Any]:
        transcript = self.transcribe()
        candidates = self.plugin.clip_candidates(
            transcript.timeline(), max_candidates=5, min_duration=8, max_duration=12
        )
        rendered = self.plugin.render_selected_clip(
            app_runtime=self.runtime,
            content_service=self.content,
            workspace_id="creator-video",
            source_asset_id=self.video_asset.id,
            selected=candidates[0],
            transcript_segments=transcript.timeline(),
            test_mode=True,
            actor="phase37-test",
        )
        return {"transcript": transcript, "candidates": candidates, "rendered": rendered}
