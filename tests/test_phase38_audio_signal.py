from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import AudioEnergySignalAnalyzer
from tests.phase38_support import Phase38Harness


class Phase38AudioSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_real_audio_analysis_penalizes_silence(self) -> None:
        analyzer = AudioEnergySignalAnalyzer()
        windows = analyzer.analyze_source(self.harness.phase38_video_path)
        self.assertGreater(len(windows), 0)
        candidates = {candidate.start_time: candidate for candidate in self.harness.baseline_candidates()}
        energetic = analyzer.score(candidates[8.0], windows)
        quiet = analyzer.score(candidates[18.0], windows)
        self.assertGreater(energetic.score, quiet.score)
        self.assertGreater(quiet.evidence["silence_ratio"], energetic.evidence["silence_ratio"])
