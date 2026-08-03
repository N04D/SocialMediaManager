from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36VideoExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_real_extraction_file_and_duration(self) -> None:
        selected = self.harness.candidates()[0]
        root = self.harness.root / "extract-test"
        root.mkdir()
        output = root / "extract.mp4"
        self.harness.plugin.extract_video_segment(
            source_path=self.harness.video_path,
            output_path=output,
            start_time=selected.start_time,
            duration=selected.duration,
            managed_root=self.harness.root,
        )
        self.assertTrue(output.exists())
        metadata = self.harness.plugin.probe_video(output)
        self.assertAlmostEqual(metadata.duration, selected.duration, delta=0.8)
        self.assertTrue(metadata.audio_present)
