from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36VideoImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_video_import_metadata_and_transcript_association(self) -> None:
        asset = self.harness.video_asset
        self.assertEqual(asset.media_type, "video")
        self.assertEqual(asset.mime_type, "video/mp4")
        self.assertGreater(asset.duration_ms, 30_000)
        self.assertEqual(asset.width, 640)
        self.assertEqual(asset.height, 360)
        metadata = asset.metadata["video_metadata"]
        self.assertGreater(metadata["fps"], 0)
        self.assertTrue(metadata["audio_present"])
        self.assertEqual(asset.metadata["transcript_status"], "imported")
        self.assertEqual(len(asset.metadata["timeline_transcript"]), 4)
