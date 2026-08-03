from __future__ import annotations

import unittest

from plugins.providers.local_transcription import LocalTranscriptionConfig, LocalTranscriptionProvider
from tests.phase37_support import Phase37Harness


class Phase37TranscriptionProviderTests(unittest.TestCase):
    def test_default_real_adapter_reports_model_unavailable_without_fake_success(self) -> None:
        provider = LocalTranscriptionProvider(provider_config=LocalTranscriptionConfig(model=""))
        health = provider.health_check()
        self.assertFalse(health["ready"])
        self.assertIn(health["status"], {"model_unavailable", "engine_unavailable"})
        self.assertFalse(health["model_autodownload"])

    def test_deterministic_provider_transcribes_managed_video(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.provider_id, "provider.transcription.local")
        self.assertGreater(len(result.segments), 2)
        self.assertIn("What makes a short worth watching", result.text)
