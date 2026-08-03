from __future__ import annotations

import unittest

from tests.phase37_support import Phase37Harness


class Phase37VideoWorkflowTests(unittest.TestCase):
    def test_upload_generate_transcript_to_rendered_short_uses_existing_chain(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe_and_render()
        self.assertGreaterEqual(len(result["candidates"]), 3)
        self.assertEqual(result["rendered"].captioned_asset.metadata["asset_type"], "short_video")
        self.assertEqual(len(result["rendered"].captioned_asset.metadata["transformation_run_ids"]), 3)
        self.assertTrue(result["rendered"].captioned_asset.metadata["captions_included"])
