from __future__ import annotations

import unittest

from media_store import get_media_asset
from tests.phase37_support import Phase37Harness


class Phase37TranscriptProvenanceTests(unittest.TestCase):
    def test_original_transcript_is_preserved_with_provider_provenance(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe()
        asset = get_media_asset(harness.video_asset.id)
        transcript = asset.metadata["transcripts"][0]
        self.assertEqual(transcript["original_transcript"], result.text)
        self.assertEqual(transcript["canonical_edited_transcript"], result.text)
        self.assertEqual(transcript["provenance"]["provider_id"], "provider.transcription.local")
        self.assertEqual(transcript["provenance"]["engine"], "deterministic_fixture")
        self.assertEqual(transcript["provenance"]["audio_asset_id"], result.audio_asset_id)
