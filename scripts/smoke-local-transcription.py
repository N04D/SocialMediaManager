#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_MODEL_PATH = Path("studio_data/models/faster-whisper-tiny")
SMOKE_TEXT = "This is a transcription test. The creator workflow can turn long videos into short clips."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real local transcription smoke test.")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="en")
    return parser.parse_args()


def require_local_model(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise RuntimeError(f"model_unavailable: {resolved}")
    return resolved


def create_speech_video(root: Path) -> Path:
    from plugins.transformations.video_repurpose.ffmpeg_boundary import run_ffmpeg

    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        raise RuntimeError("speech_fixture_unavailable: espeak-ng/espeak was not found")
    wav_path = root / "speech.wav"
    video_path = root / "speech-video.mp4"
    subprocess.run([espeak, "-w", str(wav_path), "-s", "140", SMOKE_TEXT], check=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24:duration=12",
            "-i",
            str(wav_path),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(video_path),
        ],
        timeout=60,
    )
    return video_path


def token_overlap(text: str) -> float:
    expected = {token.strip(".,").lower() for token in SMOKE_TEXT.split()}
    actual = {token.strip(".,").lower() for token in text.split()}
    return len(expected & actual) / max(1, len(expected))


def smoke_payload(args: argparse.Namespace) -> dict[str, Any]:
    from plugin_runtime import bootstrap_plugins
    from tests.phase35_support import Phase35Harness

    model_path = require_local_model(Path(args.model_path))
    with tempfile.TemporaryDirectory(prefix="real-transcription-smoke-") as tmp:
        fixture_root = Path(tmp)
        video_path = create_speech_video(fixture_root)
        harness = Phase35Harness()
        try:
            harness.config.transcription_model = str(model_path)
            harness.config.transcription_device = args.device
            harness.config.transcription_compute_type = args.compute_type
            harness.config.transcription_language = args.language
            harness.runtime = bootstrap_plugins(harness.config, strict=False)
            harness.content = harness.runtime.content_service(harness.config)
            transcriber = harness.runtime.transcription_provider()
            repurpose = harness.runtime.get_plugin_service("plugin.video_repurpose", "transformation_service")
            health = transcriber.health_check()
            if not health.get("ready"):
                raise RuntimeError(f"provider_not_ready: {health}")
            source_asset = repurpose.import_long_form_video(
                app_runtime=harness.runtime,
                workspace_id="real-transcription-smoke",
                local_path=video_path,
                created_by="smoke-local-transcription",
                source_reference="real_speech_fixture",
            )
            started = time.perf_counter()
            transcript = transcriber.transcribe(
                app_runtime=harness.runtime,
                content_service=harness.content,
                workspace_id="real-transcription-smoke",
                source_asset_id=source_asset.id,
                language=args.language,
                actor="smoke-local-transcription",
            )
            transcription_seconds = round(time.perf_counter() - started, 3)
            timeline = transcript.timeline()
            candidates = repurpose.clip_candidates(timeline, max_candidates=5, min_duration=1, max_duration=20)
            if not candidates:
                raise RuntimeError("clip_candidate_unavailable")
            rendered = repurpose.render_selected_clip(
                app_runtime=harness.runtime,
                content_service=harness.content,
                workspace_id="real-transcription-smoke",
                source_asset_id=source_asset.id,
                selected=candidates[0],
                transcript_segments=timeline,
                test_mode=True,
                actor="smoke-local-transcription",
            )
            overlap = token_overlap(transcript.text)
            if not transcript.text.strip() or not timeline or overlap < 0.15:
                raise RuntimeError(f"transcript_quality_failed: overlap={overlap} text={transcript.text!r}")
            return {
                "status": "PASS",
                "engine": transcript.engine,
                "model": transcript.model,
                "model_path": str(model_path),
                "model_size_bytes": sum(p.stat().st_size for p in model_path.rglob("*") if p.is_file()),
                "device": args.device,
                "compute_type": args.compute_type,
                "input_duration": source_asset.duration_ms / 1000,
                "transcription_seconds": transcription_seconds,
                "text": transcript.text,
                "segment_count": len(timeline),
                "segments": [
                    {"start": segment.start_time, "end": segment.end_time, "text": segment.text} for segment in timeline
                ],
                "token_overlap": round(overlap, 3),
                "audio_asset_id": transcript.audio_asset_id,
                "transcription_run_id": transcript.run_id,
                "candidate_count": len(candidates),
                "selected_candidate": candidates[0].candidate_id,
                "short_asset_id": rendered.captioned_asset.id,
                "caption_segments": rendered.caption_segments,
                "provider_health": health,
            }
        finally:
            harness.close()


def main() -> int:
    args = parse_args()
    try:
        payload = smoke_payload(args)
    except Exception as exc:
        print("REAL LOCAL TRANSCRIPTION SMOKE: BLOCKED")
        print(type(exc).__name__, str(exc))
        return 2
    print("REAL LOCAL TRANSCRIPTION SMOKE: PASS")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
