from __future__ import annotations

import unittest

from media_store import list_media_assets
from src.core.media import MediaNotFoundError
from tests.phase36_support import Phase36Harness


class Phase36FailureSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_failure_does_not_create_valid_short_asset_and_duplicate_reuses_existing(self) -> None:
        candidate = self.harness.candidates()[0]
        before = len(
            [
                asset
                for asset in list_media_assets(workspace_id="creator-video")
                if asset.metadata.get("asset_type") == "short_video"
            ]
        )
        with self.assertRaises(MediaNotFoundError):
            self.harness.plugin.render_selected_clip(
                app_runtime=self.harness.runtime,
                content_service=self.harness.content,
                workspace_id="creator-video",
                source_asset_id="missing",
                selected=candidate,
                transcript_segments=self.harness.timeline,
                test_mode=True,
            )
        after = len(
            [
                asset
                for asset in list_media_assets(workspace_id="creator-video")
                if asset.metadata.get("asset_type") == "short_video"
            ]
        )
        self.assertEqual(before, after)
        first = self.harness.render_candidate()["result"]
        second = self.harness.render_candidate()["result"]
        self.assertFalse(first.duplicate_reused)
        self.assertTrue(second.duplicate_reused)
        self.assertEqual(first.captioned_asset.id, second.captioned_asset.id)
