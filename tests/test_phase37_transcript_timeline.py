from __future__ import annotations

import unittest

from tests.phase37_support import Phase37Harness


class Phase37TranscriptTimelineTests(unittest.TestCase):
    def test_transcript_maps_to_existing_timeline_contract_for_clip_selector(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe()
        timeline = result.timeline()
        candidates = harness.plugin.clip_candidates(timeline, max_candidates=5, min_duration=8, max_duration=12)
        self.assertEqual(timeline[0].start_time, 0.0)
        self.assertGreaterEqual(len(candidates), 3)
        self.assertIn("Strong standalone opening", candidates[0].reason)
