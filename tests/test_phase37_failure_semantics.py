from __future__ import annotations

import unittest

from plugins.providers.local_transcription import TranscriptionError, TranscriptSegment
from tests.phase37_support import Phase37Harness


class Phase37FailureSemanticsTests(unittest.TestCase):
    def test_missing_audio_does_not_create_success_transcript(self) -> None:
        harness = Phase37Harness(with_audio=False)
        self.addCleanup(harness.close)
        with self.assertRaises(TranscriptionError) as ctx:
            harness.transcribe()
        self.assertEqual(ctx.exception.code, "missing_audio")

    def test_invalid_provider_output_is_rejected(self) -> None:
        harness = Phase37Harness(
            invalid_segments=(TranscriptSegment(segment_id="bad", start_time=4.0, end_time=3.0, text="Broken timing"),)
        )
        self.addCleanup(harness.close)
        with self.assertRaises(TranscriptionError) as ctx:
            harness.transcribe()
        self.assertEqual(ctx.exception.code, "provider_output_invalid")

    def test_duplicate_and_explicit_retranscription_semantics(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        first = harness.transcribe()
        reused = harness.transcribe()
        new = harness.transcribe(force_new=True)
        self.assertEqual(first.run_id, reused.run_id)
        self.assertNotEqual(first.run_id, new.run_id)
