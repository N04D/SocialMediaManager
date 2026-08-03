from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import SceneBoundarySignalAnalyzer
from tests.phase38_support import Phase38Harness


class Phase38SceneSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_real_scene_detection_produces_boundary_evidence(self) -> None:
        analyzer = SceneBoundarySignalAnalyzer()
        changes = analyzer.analyze_source(self.harness.phase38_video_path)
        self.assertGreaterEqual(len(changes), 2)
        candidate = next(candidate for candidate in self.harness.baseline_candidates() if candidate.start_time == 8.0)
        result = analyzer.score(candidate, changes)
        self.assertEqual(result.status, "available")
        self.assertIn("scene_changes", result.evidence)
