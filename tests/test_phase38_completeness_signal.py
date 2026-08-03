from __future__ import annotations

import unittest
from dataclasses import replace

from plugins.transformations.video_repurpose.clip_intelligence import CompletenessSignalAnalyzer
from tests.phase38_support import Phase38Harness


class Phase38CompletenessSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_natural_boundaries_score_above_incomplete_ending(self) -> None:
        candidate = self.harness.baseline_candidates()[0]
        incomplete = replace(candidate, transcript_excerpt="this starts mid thought and ends with")
        analyzer = CompletenessSignalAnalyzer()
        complete = analyzer.score(candidate, self.harness.timeline)
        incomplete_result = analyzer.score(incomplete, self.harness.timeline)
        self.assertGreater(complete.score, incomplete_result.score)
        self.assertIn("suggested_end", incomplete_result.evidence)
