from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import ClipSignalResult


class Phase38ClipSignalContractTests(unittest.TestCase):
    def test_signal_contract_validates_normalized_scores(self) -> None:
        result = ClipSignalResult(
            signal_id="clip.signal.semantic",
            candidate_id="candidate-1",
            start_time=0,
            end_time=10,
            score=0.72,
            reason="Complete standalone thought",
        )
        result.validate()
        with self.assertRaises(ValueError):
            ClipSignalResult(
                signal_id="clip.signal.semantic",
                candidate_id="candidate-1",
                start_time=0,
                end_time=10,
                score=1.2,
            ).validate()

    def test_unavailable_is_not_false_zero(self) -> None:
        result = ClipSignalResult(
            signal_id="clip.signal.speaker_boundary",
            candidate_id="candidate-1",
            start_time=0,
            end_time=10,
            score=None,
            status="unavailable",
            reason="Speaker labels unavailable",
        )
        result.validate()
        self.assertFalse(result.available())
        self.assertIsNone(result.score)
