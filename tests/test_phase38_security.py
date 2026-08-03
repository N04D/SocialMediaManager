from __future__ import annotations

import unittest
from pathlib import Path


class Phase38SecurityTests(unittest.TestCase):
    def test_clip_intelligence_has_no_cloud_ai_or_provider_coupling(self) -> None:
        source = Path("plugins/transformations/video_repurpose/clip_intelligence.py").read_text(encoding="utf-8")
        forbidden = [
            "OpenAI",
            "Anthropic",
            "Gemini",
            "requests.",
            "httpx.",
            "socket.socket",
            "faster_whisper",
            "LinkedIn",
            "TikTok",
            "Instagram",
            "Shopify",
            "publish(",
            "payment",
            "order",
            "production_ready=true",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, source)

    def test_media_analysis_uses_ffmpeg_boundary_without_shell_bypass(self) -> None:
        source = Path("plugins/transformations/video_repurpose/clip_intelligence.py").read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("subprocess", source)

    def test_video_repurpose_has_no_transcription_provider_knowledge(self) -> None:
        source = Path("plugins/transformations/video_repurpose/plugin.py").read_text(encoding="utf-8")
        self.assertNotIn("faster_whisper", source)
        self.assertNotIn("WhisperLocal", source)
        self.assertNotIn("provider.transcription.local", source)
