from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import (
    AudioEnergySignalAnalyzer,
    ClipSignalFusionRanker,
    FusionConfig,
    SpeakerBoundarySignalAnalyzer,
)
from tests.phase38_support import Phase38Harness


class Phase38SignalAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_missing_speaker_and_audio_are_unavailable_not_zero(self) -> None:
        candidate = self.harness.baseline_candidates()[0]
        speaker = SpeakerBoundarySignalAnalyzer().score(candidate, self.harness.timeline)
        audio = AudioEnergySignalAnalyzer().score(candidate, None)
        self.assertEqual(speaker.status, "unavailable")
        self.assertIsNone(speaker.score)
        self.assertEqual(audio.status, "unavailable")
        ranked = ClipSignalFusionRanker(
            FusionConfig(semantic_weight=0, hook_weight=0, completeness_weight=0, audio_weight=1)
        ).rank(
            [candidate],
            {"clip.signal.audio_energy": [audio]},
        )
        self.assertEqual(ranked[0].final_score, 0.0)
        self.assertIn("clip.signal.audio_energy", ranked[0].signals_unavailable)
