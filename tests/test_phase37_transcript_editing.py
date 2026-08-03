from __future__ import annotations

import unittest

from media_store import get_media_asset
from tests.phase37_support import Phase37Harness


class Phase37TranscriptEditingTests(unittest.TestCase):
    def test_canonical_edit_changes_canonical_not_original(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe()
        transcript_id = result.transcript_asset.asset_id
        edited = "Edited canonical transcript for the creator workspace."
        harness.transcription_provider.edit_canonical_transcript(
            source_asset_id=harness.video_asset.id,
            transcript_asset_id=transcript_id,
            edited_text=edited,
            edited_by="creator",
        )
        asset = get_media_asset(harness.video_asset.id)
        transcript = asset.metadata["transcripts"][0]
        self.assertNotEqual(transcript["original_transcript"], edited)
        self.assertEqual(transcript["canonical_edited_transcript"], edited)
        self.assertTrue(transcript["canonical_changed"])
