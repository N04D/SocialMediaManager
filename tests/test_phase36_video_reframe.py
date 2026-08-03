from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36VideoReframeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_landscape_source_renders_nine_by_sixteen(self) -> None:
        rendered = self.harness.render_candidate(0)["result"]
        asset = rendered.captioned_asset
        self.assertEqual(rendered.reframe_strategy, "center_crop")
        self.assertEqual(asset.width, 360)
        self.assertEqual(asset.height, 640)
        self.assertEqual(round(asset.width / asset.height, 3), 0.562)
        self.assertEqual(asset.metadata["reframe_strategy"], "center_crop")
