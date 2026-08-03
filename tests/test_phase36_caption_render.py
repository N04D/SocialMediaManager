from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36CaptionRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_caption_timing_is_clip_local_and_preserves_original_timestamps(self) -> None:
        candidate = next(candidate for candidate in self.harness.candidates() if candidate.start_time == 10.0)
        subset = self.harness.plugin.caption_subset(self.harness.timeline, candidate)
        self.assertEqual(subset[0]["start"], 0.0)
        self.assertEqual(subset[0]["end"], 10.0)
        self.assertEqual(subset[0]["original_start"], 10.0)
        self.assertEqual(subset[0]["original_end"], 20.0)
        index = self.harness.candidates().index(candidate)
        rendered = self.harness.render_candidate(index)["result"]
        self.assertTrue(rendered.captioned_asset.metadata["captions_included"])
        self.assertTrue(rendered.captioned_asset.metadata["caption_segments"][0]["text"])
