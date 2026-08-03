from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36ClipSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_candidate_ranking_constraints_and_explicit_selection(self) -> None:
        candidates = self.harness.candidates()
        self.assertEqual(len(candidates), 4)
        self.assertGreaterEqual(candidates[0].score, candidates[1].score)
        for candidate in candidates:
            self.assertGreaterEqual(candidate.duration, 8)
            self.assertLessEqual(candidate.duration, 12)
            self.assertTrue(candidate.title)
            self.assertTrue(candidate.transcript_excerpt.endswith((".", "?", "!")))
            self.assertIn("complete thought", candidate.reason)
        selected = next(candidate for candidate in candidates if candidate.start_time == 10.0)
        self.assertEqual(selected.start_time, 10.0)
        self.assertEqual(selected.end_time, 20.0)
