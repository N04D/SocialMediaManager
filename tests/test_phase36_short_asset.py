from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36ShortAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_output_asset_contract_is_real_and_preview_ready(self) -> None:
        rendered = self.harness.render_candidate()["result"]
        asset = rendered.captioned_asset
        self.assertEqual(asset.metadata["asset_type"], "short_video")
        self.assertEqual(asset.status, "available")
        self.assertEqual(asset.mime_type, "video/mp4")
        self.assertGreater(asset.file_size, 0)
        self.assertEqual(asset.metadata["source_asset_id"], self.harness.video_asset.id)
        self.assertEqual(len(asset.metadata["transformation_run_ids"]), 3)
        self.assertTrue(asset.metadata["preview_ready"])
        self.assertEqual(
            {variant.asset_type for variant in rendered.variants},
            {"variant.social_text", "variant.short_caption", "variant.article"},
        )

    def test_multiple_independent_shorts_under_same_source(self) -> None:
        first = self.harness.render_candidate(0)["result"]
        second = self.harness.render_candidate(1)["result"]

        self.assertEqual(first.captioned_asset.metadata["source_asset_id"], self.harness.video_asset.id)
        self.assertEqual(second.captioned_asset.metadata["source_asset_id"], self.harness.video_asset.id)
        self.assertNotEqual(first.selected_candidate.candidate_id, second.selected_candidate.candidate_id)
        self.assertNotEqual(first.captioned_asset.id, second.captioned_asset.id)
        self.assertEqual(first.captioned_asset.metadata["asset_type"], "short_video")
        self.assertEqual(second.captioned_asset.metadata["asset_type"], "short_video")
