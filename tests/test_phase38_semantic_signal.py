from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import SemanticSignalAnalyzer
from tests.phase38_support import Phase38Harness


class Phase38SemanticSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_standalone_segment_scores_above_context_dependent_segment(self) -> None:
        candidates = {candidate.start_time: candidate for candidate in self.harness.baseline_candidates()}
        analyzer = SemanticSignalAnalyzer()
        gold = analyzer.score(candidates[8.0], self.harness.timeline)
        weak = analyzer.score(candidates[18.0], self.harness.timeline)
        self.assertGreater(gold.score, weak.score)
        self.assertIn("Complete", gold.reason)
        self.assertIn("context", weak.reason)
