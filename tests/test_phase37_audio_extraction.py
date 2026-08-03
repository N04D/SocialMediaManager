from __future__ import annotations

import unittest

from media_store import get_media_asset
from tests.phase37_support import Phase37Harness


class Phase37AudioExtractionTests(unittest.TestCase):
    def test_video_input_extracts_managed_audio_asset_safely(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe()
        audio = get_media_asset(result.audio_asset_id)
        self.assertIsNotNone(audio)
        self.assertEqual(audio.metadata["asset_type"], "audio")
        self.assertEqual(audio.metadata["sample_rate"], 16000)
        self.assertEqual(audio.metadata["channels"], 1)
        self.assertEqual(audio.metadata["source_asset_id"], harness.video_asset.id)
