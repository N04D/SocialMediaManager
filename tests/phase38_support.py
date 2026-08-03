from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.transformations.video_repurpose import VideoRepurposePlugin
from plugins.transformations.video_repurpose.clip_intelligence import (
    AudioEnergySignalAnalyzer,
    ClipSignalFusionRanker,
    ClipSignalResult,
    CompletenessSignalAnalyzer,
    FusionConfig,
    HookSignalAnalyzer,
    RankedClipCandidate,
    SceneBoundarySignalAnalyzer,
    SemanticSignalAnalyzer,
)
from plugins.transformations.video_repurpose.ffmpeg_boundary import run_ffmpeg
from tests.phase36_support import Phase36Harness

PHASE38_TRANSCRIPT = """00:00:00.000 --> 00:00:08.000
What happened before this is something we covered earlier and then we are still setting up the idea.

00:00:08.000 --> 00:00:18.000
Why is patience not passive? It turns pressure into steady progress and gives the creator one complete choice.

00:00:18.000 --> 00:00:26.000
And then there is a long quiet part where this and that continue without a clear point.

00:00:26.000 --> 00:00:36.000
Here is the simple lesson. Start with one clear promise, finish the thought, and choose the moment.
"""


class Phase38Harness(Phase36Harness):
    def __init__(self) -> None:
        super().__init__()
        self.phase38_video_path = self.root / "fixtures" / "phase38-multimodal.mp4"
        self.create_multimodal_fixture(self.phase38_video_path)
        self.timeline = self.plugin.parse_timestamped_transcript(PHASE38_TRANSCRIPT)

    @staticmethod
    def create_multimodal_fixture(path: Path) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        specs = (
            ("red", "sine=frequency=330:duration=8", 8),
            ("blue", "sine=frequency=880:duration=10", 10),
            ("green", "anullsrc=channel_layout=mono:sample_rate=44100:d=8", 8),
            ("yellow", "sine=frequency=660:duration=10", 10),
        )
        parts: list[Path] = []
        for index, (color, audio, duration) in enumerate(specs):
            segment = path.parent / f"phase38-segment-{index}.mp4"
            parts.append(segment)
            if segment.exists():
                continue
            run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s=320x180:r=24:d={duration}",
                    "-f",
                    "lavfi",
                    "-i",
                    audio,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(segment),
                ],
                timeout=60,
            )
        concat = path.parent / "phase38-concat.txt"
        concat.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
        run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(path)],
            timeout=60,
        )

    def baseline_candidates(self):
        return self.plugin.clip_candidates(self.timeline, max_candidates=4, min_duration=8, max_duration=12)

    def multimodal_candidates(self) -> list[RankedClipCandidate]:
        return self.plugin.multimodal_clip_candidates(
            self.timeline,
            source_video_path=self.phase38_video_path,
            max_candidates=4,
            min_duration=8,
            max_duration=12,
        )

    def signals_for_baseline(self) -> dict[str, list[ClipSignalResult]]:
        candidates = self.baseline_candidates()
        audio = AudioEnergySignalAnalyzer()
        scene = SceneBoundarySignalAnalyzer()
        windows = audio.analyze_source(self.phase38_video_path)
        changes = scene.analyze_source(self.phase38_video_path)
        return {
            "clip.signal.semantic": [
                SemanticSignalAnalyzer().score(candidate, self.timeline) for candidate in candidates
            ],
            "clip.signal.hook": [HookSignalAnalyzer().score(candidate, self.timeline) for candidate in candidates],
            "clip.signal.completeness": [
                CompletenessSignalAnalyzer().score(candidate, self.timeline) for candidate in candidates
            ],
            "clip.signal.audio_energy": [audio.score(candidate, windows) for candidate in candidates],
            "clip.signal.scene_boundary": [scene.score(candidate, changes) for candidate in candidates],
        }

    @staticmethod
    def candidate_quality(start_time: float) -> int:
        if start_time in {8.0, 26.0}:
            return 2
        if start_time == 18.0:
            return 0
        return 1

    def evaluation(self) -> dict[str, Any]:
        baseline = self.baseline_candidates()
        multimodal = self.multimodal_candidates()
        baseline_top3 = sum(1 for candidate in baseline[:3] if self.candidate_quality(candidate.start_time) == 2)
        multimodal_top3 = sum(
            1 for ranked in multimodal[:3] if self.candidate_quality(ranked.candidate.start_time) == 2
        )
        baseline_top2_quality = sum(self.candidate_quality(candidate.start_time) for candidate in baseline[:2])
        multimodal_top2_quality = sum(self.candidate_quality(ranked.candidate.start_time) for ranked in multimodal[:2])
        return {
            "baseline_top1": baseline[0].start_time,
            "multimodal_top1": multimodal[0].candidate.start_time,
            "baseline_top1_quality": self.candidate_quality(baseline[0].start_time),
            "multimodal_top1_quality": self.candidate_quality(multimodal[0].candidate.start_time),
            "baseline_top3_gold_hits": baseline_top3,
            "multimodal_top3_gold_hits": multimodal_top3,
            "baseline_top2_quality": baseline_top2_quality,
            "multimodal_top2_quality": multimodal_top2_quality,
        }


def rank_with_replacement_signal(
    plugin: VideoRepurposePlugin,
    candidates: list[Any],
    replacement: ClipSignalResult,
) -> list[RankedClipCandidate]:
    signals = {
        "clip.signal.hook": [replacement],
        "clip.signal.semantic": [
            ClipSignalResult(
                signal_id="clip.signal.semantic",
                candidate_id=candidate.candidate_id,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                score=0.5,
                reason="Neutral semantic replacement test",
            )
            for candidate in candidates
        ],
    }
    return ClipSignalFusionRanker(FusionConfig(hook_weight=1.0, semantic_weight=0.0)).rank(candidates, signals)
