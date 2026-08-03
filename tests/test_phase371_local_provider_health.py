from __future__ import annotations

import unittest

from plugins.providers.local_transcription import LocalTranscriptionConfig, LocalTranscriptionProvider


class Phase371LocalProviderHealthTests(unittest.TestCase):
    def test_invalid_or_missing_model_is_not_ready(self) -> None:
        provider = LocalTranscriptionProvider(provider_config=LocalTranscriptionConfig(model="missing-model"))
        health = provider.health_check()
        self.assertFalse(health["ready"])
        self.assertEqual(health["status"], "model_unavailable")

    def test_remote_model_id_is_not_treated_as_local_ready(self) -> None:
        provider = LocalTranscriptionProvider(
            provider_config=LocalTranscriptionConfig(model="Systran/faster-whisper-tiny")
        )
        health = provider.health_check()
        self.assertFalse(health["ready"])
        self.assertEqual(health["status"], "model_unavailable")
