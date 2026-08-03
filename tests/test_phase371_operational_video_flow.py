from __future__ import annotations

import unittest

from tests.phase37_support import Phase37Harness


class Phase371OperationalVideoFlowTests(unittest.TestCase):
    def test_regression_video_flow_still_uses_provider_contract(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe_and_render()
        self.assertGreaterEqual(len(result["candidates"]), 1)
        self.assertTrue(result["rendered"].captioned_asset.metadata["captions_included"])
