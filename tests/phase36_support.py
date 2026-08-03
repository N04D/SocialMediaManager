from __future__ import annotations

from pathlib import Path
from typing import Any

from media_store import save_media_asset
from plugins.transformations.video_repurpose import VideoRepurposePlugin
from plugins.transformations.video_repurpose.ffmpeg_boundary import run_ffmpeg
from tests.phase35_support import Phase35Harness

PHASE36_TRANSCRIPT = """00:00:00.000 --> 00:00:10.000
What makes a short worth watching? It starts with one clear promise and ends with one complete idea.

00:00:10.000 --> 00:00:20.000
Why does Sabr matter in daily creative work? It helps you keep moving without rushing the result.

00:00:20.000 --> 00:00:30.000
When a long story becomes heavy, choose the moment where the viewer can understand the whole lesson.

00:00:30.000 --> 00:00:40.000
A simple creator workflow is upload, choose, render, preview, and then write the supporting caption.
"""


class Phase36Harness(Phase35Harness):
    def __init__(self) -> None:
        super().__init__()
        self.plugin: VideoRepurposePlugin = self.runtime.get_plugin_service(
            "plugin.video_repurpose", "transformation_service"
        )
        self.video_path = self.root / "fixtures" / "phase36-longform.mp4"
        self.video_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_synthetic_video(self.video_path, width=640, height=360, duration=40)
        self.timeline = self.plugin.parse_timestamped_transcript(PHASE36_TRANSCRIPT)
        self.video_asset = self.plugin.import_long_form_video(
            app_runtime=self.runtime,
            workspace_id="creator-video",
            local_path=self.video_path,
            created_by="phase36-test",
            source_reference="synthetic_phase36_longform",
        )
        self.video_asset.metadata["transcript_status"] = "imported"
        self.video_asset.metadata["timeline_transcript"] = [segment.__dict__ for segment in self.timeline]
        save_media_asset(self.video_asset)

    @staticmethod
    def create_synthetic_video(path: Path, *, width: int, height: int, duration: int) -> None:
        if path.exists():
            return
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size={width}x{height}:rate=24:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=880:duration={duration}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-shortest",
                str(path),
            ],
            timeout=60,
        )

    def candidates(self):
        return self.plugin.clip_candidates(self.timeline, max_candidates=5, min_duration=8, max_duration=12)

    def render_candidate(self, index: int = 0) -> dict[str, Any]:
        candidate = self.candidates()[index]
        result = self.plugin.render_selected_clip(
            app_runtime=self.runtime,
            content_service=self.content,
            workspace_id="creator-video",
            source_asset_id=self.video_asset.id,
            selected=candidate,
            transcript_segments=self.timeline,
            test_mode=True,
            actor="phase36-test",
        )
        return {"candidate": candidate, "result": result}
