from __future__ import annotations

import unittest

from tests.phase38_support import Phase38Harness


class Phase38BaselineComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_baseline_is_retained_and_multimodal_improves_fixture_quality(self) -> None:
        baseline = self.harness.baseline_candidates()
        multimodal = self.harness.multimodal_candidates()
        self.assertEqual(len(baseline), 4)
        self.assertEqual(len(multimodal), 4)
        self.assertEqual(baseline[0].provenance["strategy"], "deterministic_v1")
        evaluation = self.harness.evaluation()
        self.assertGreaterEqual(evaluation["multimodal_top1_quality"], evaluation["baseline_top1_quality"])
        self.assertGreaterEqual(evaluation["multimodal_top3_gold_hits"], evaluation["baseline_top3_gold_hits"])
        self.assertTrue(
            evaluation["multimodal_top1_quality"] > evaluation["baseline_top1_quality"]
            or evaluation["multimodal_top3_gold_hits"] > evaluation["baseline_top3_gold_hits"]
            or evaluation["multimodal_top2_quality"] > evaluation["baseline_top2_quality"]
        )

    def test_top_multimodal_candidate_can_feed_existing_render_chain(self) -> None:
        ranked = self.harness.multimodal_candidates()[0]
        selected = ranked.to_candidate_with_provenance()
        result = self.harness.plugin.render_selected_clip(
            app_runtime=self.harness.runtime,
            content_service=self.harness.content,
            workspace_id="creator-video",
            source_asset_id=self.harness.video_asset.id,
            selected=selected,
            transcript_segments=self.harness.timeline,
            test_mode=True,
            actor="phase38-test",
        )
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.captioned_asset.metadata["captions_included"])
