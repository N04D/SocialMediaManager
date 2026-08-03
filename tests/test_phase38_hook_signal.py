from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import HookSignalAnalyzer
from tests.phase38_support import Phase38Harness


class Phase38HookSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_question_or_claim_opening_scores_above_weak_opening(self) -> None:
        candidates = {candidate.start_time: candidate for candidate in self.harness.baseline_candidates()}
        analyzer = HookSignalAnalyzer()
        strong = analyzer.score(candidates[8.0], self.harness.timeline)
        weak = analyzer.score(candidates[18.0], self.harness.timeline)
        self.assertGreater(strong.score, weak.score)
        self.assertIn("Strong opening", strong.reason)
        self.assertIn("Weak opening", weak.reason)
