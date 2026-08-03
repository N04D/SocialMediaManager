from __future__ import annotations

import unittest

from tests.phase38_support import Phase38Harness


class Phase38RankingProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_ranking_preserves_signals_weights_and_candidate_generation(self) -> None:
        ranked = self.harness.multimodal_candidates()[0]
        candidate = ranked.to_candidate_with_provenance()
        ranking = candidate.provenance["ranking"]
        self.assertEqual(ranking["ranking_version"], "multimodal_fusion_v1")
        self.assertIn("clip.signal.semantic", ranking["signals_used"])
        self.assertIn("weights", ranking)
        self.assertEqual(candidate.provenance["strategy"], "deterministic_v1")

    def test_user_selection_and_manual_adjustment_are_learning_ready(self) -> None:
        ranked = self.harness.multimodal_candidates()[0]
        selected = self.harness.plugin.selected_ranked_candidate(
            ranked,
            selected_at="2026-08-03T12:00:00Z",
            adjusted_start=ranked.candidate.start_time + 0.5,
        )
        self.assertEqual(selected.selection_status, "manually_adjusted")
        self.assertEqual(selected.user_adjustment["status"], "manually_adjusted")
