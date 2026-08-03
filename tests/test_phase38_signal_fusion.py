from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import (
    ClipSignalFusionRanker,
    ClipSignalResult,
    FusionConfig,
)
from tests.phase38_support import Phase38Harness


class Phase38SignalFusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_fusion_uses_normalized_weights_and_orders_deterministically(self) -> None:
        ranked = self.harness.multimodal_candidates()
        self.assertEqual([item.rank for item in ranked], [1, 2, 3, 4])
        self.assertGreaterEqual(ranked[0].final_score, ranked[1].final_score)
        self.assertIn("ranking_strategy", ranked[0].provenance)

    def test_invalid_weight_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FusionConfig(semantic_weight=-1).validate()

    def test_invalid_signal_score_is_rejected(self) -> None:
        candidate = self.harness.baseline_candidates()[0]
        signals = {
            "clip.signal.semantic": [
                ClipSignalResult(
                    signal_id="clip.signal.semantic",
                    candidate_id=candidate.candidate_id,
                    start_time=candidate.start_time,
                    end_time=candidate.end_time,
                    score=2.0,
                )
            ]
        }
        with self.assertRaises(ValueError):
            ClipSignalFusionRanker(FusionConfig(semantic_weight=1, hook_weight=0)).rank([candidate], signals)
