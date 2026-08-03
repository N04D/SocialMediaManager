from __future__ import annotations

import unittest

from plugins.providers.local_transcription import (
    DeterministicTranscriptionEngine,
    LocalTranscriptionConfig,
    LocalTranscriptionProvider,
)
from tests.phase37_support import Phase37Harness


class Phase37ProviderResolutionTests(unittest.TestCase):
    def test_registry_resolves_transcription_capability(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        providers = harness.runtime.registry.providers_for("transcription.media")
        self.assertEqual(providers[0].id, "provider.transcription.local")
        service = harness.runtime.transcription_provider()
        self.assertEqual(service.provider_id, "provider.transcription.local")

    def test_provider_a_b_interchangeability_keeps_clip_plugin_unchanged(self) -> None:
        provider_a = LocalTranscriptionProvider(
            provider_config=LocalTranscriptionConfig(engine="deterministic_fixture", model="a"),
            engine=DeterministicTranscriptionEngine(),
        )
        provider_b = LocalTranscriptionProvider(
            provider_config=LocalTranscriptionConfig(engine="deterministic_fixture", model="b"),
            engine=DeterministicTranscriptionEngine(language="nl"),
        )
        self.assertEqual(provider_a.contract.produces, provider_b.contract.produces)
        self.assertIn("timeline.transcript", provider_a.capabilities)
        self.assertIn("timeline.transcript", provider_b.capabilities)
